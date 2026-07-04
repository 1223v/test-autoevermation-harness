#!/usr/bin/env node
/* MCP·훅 크로스플랫폼 진입점 — Windows 네이티브 + macOS/Linux.
 *
 * .mcp.json/hooks.json은 exec form(`command: "node"` + args)으로 이 파일을 실행한다.
 * 공식 문서 근거: 훅/플러그인 exec form은 셸을 거치지 않고 실행 파일을 직접 spawn하며,
 * "node + 스크립트 경로 패턴은 node.exe가 실제 바이너리이므로 모든 플랫폼에서 동작"(hooks 문서).
 * POSIX 전용이던 run-server.sh는 수동 폴백으로 유지된다(동작 패리티 유지 대상).
 *
 * 사용:
 *   node launch.cjs <server.py> [args...]      # .mcp.json — Python+의존성 보장 후 bootstrap.py 경유 서버 실행
 *   node launch.cjs --ensure-only              # SessionStart 훅 — 준비만 하고 종료(실패 시 exit 2 + stderr 안내)
 *   node launch.cjs script <script.py> [args]  # 훅/statusline — stdlib 전용 파이썬 스크립트 실행(venv 불필요)
 *
 * 동작:
 * 1) PATH의 Python 3.10+ 존중 (Windows: `py -3` → `python` → `python3` / POSIX: `python3` → 3.13…3.10).
 *    후보가 통과하면 sys.executable 절대경로로 정규화해 사용(Windows Store 가짜 python.exe는 버전 체크에서 걸러짐).
 * 2) 없으면 uv(공식 standalone installer, 무-sudo)로 관리형 Python을 1회 설치 후
 *    ${CLAUDE_PLUGIN_DATA}/python-path 에 고정. POSIX: install.sh(curl|wget→sh), Windows: install.ps1(powershell irm|iex).
 *    비활성화: HARNESS_AUTO_PYTHON=0.
 * 3) 동시 기동(서버 3개+훅) 경쟁은 mkdirSync 락으로 직렬화(run-server.sh와 동일 방식).
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const IS_WIN = process.platform === "win32";
const SCRIPT_DIR = __dirname;
const DATA_DIR = process.env.CLAUDE_PLUGIN_DATA || path.join(SCRIPT_DIR, ".plugin-data");
const PIN_FILE = path.join(DATA_DIR, "python-path");
const LOCK_DIR = path.join(DATA_DIR, ".python-install.lock");
const UV_PY_VERSION = "3.12";
// 3.10+이면 sys.executable을 출력하고 0으로 종료 — 검사와 경로 정규화를 한 번에.
const CHECK_AND_PRINT =
  "import sys; sys.exit(1) if sys.version_info < (3, 10) else print(sys.executable)";

function log(msg) {
  process.stderr.write(`test-autoevermation-harness-plugin launch: ${msg}\n`);
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** 후보(cmd + 선행 인자)를 실행해 3.10+이면 정규화된 절대경로를 돌려준다. */
function probePython(cmd, preArgs) {
  try {
    const r = spawnSync(cmd, [...preArgs, "-c", CHECK_AND_PRINT], {
      encoding: "utf8",
      timeout: 15000,
      windowsHide: true,
    });
    if (r.status === 0 && r.stdout) {
      const p = r.stdout.trim();
      if (p && fs.existsSync(p)) return p;
    }
  } catch (_) {
    /* 후보 없음 — 다음 후보로 */
  }
  return null;
}

function findSystemPython() {
  const candidates = IS_WIN
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python3.13", []], ["python3.12", []], ["python3.11", []], ["python3.10", []], ["python", []]];
  for (const [cmd, pre] of candidates) {
    const p = probePython(cmd, pre);
    if (p) return p;
  }
  return null;
}

function pinnedPython() {
  try {
    const p = fs.readFileSync(PIN_FILE, "utf8").trim();
    if (p) return probePython(p, []);
  } catch (_) {
    /* pin 없음 */
  }
  return null;
}

function findUv() {
  const home = os.homedir();
  const names = IS_WIN
    ? ["uv", path.join(home, ".local", "bin", "uv.exe"), path.join(home, ".cargo", "bin", "uv.exe")]
    : ["uv", path.join(home, ".local", "bin", "uv"), path.join(home, ".cargo", "bin", "uv")];
  for (const u of names) {
    try {
      const r = spawnSync(u, ["--version"], { timeout: 15000, windowsHide: true });
      if (r.status === 0) return u;
    } catch (_) {
      /* 다음 후보 */
    }
  }
  return null;
}

function installUv() {
  log("installing uv (user-local, no sudo; https://astral.sh/uv) ...");
  let r;
  if (IS_WIN) {
    // uv 공식 Windows 설치 명령(astral 문서): powershell -ExecutionPolicy ByPass -c "irm .../install.ps1 | iex"
    r = spawnSync(
      "powershell.exe",
      ["-ExecutionPolicy", "ByPass", "-NoProfile", "-c", "irm https://astral.sh/uv/install.ps1 | iex"],
      { stdio: ["ignore", "inherit", "inherit"], timeout: 600000, windowsHide: true },
    );
  } else {
    // POSIX에서 sh는 보장된다 — 파이프 실행만 셸에 위임.
    const dl = spawnSync("sh", ["-c", "command -v curl >/dev/null 2>&1 && echo curl || { command -v wget >/dev/null 2>&1 && echo wget; }"], { encoding: "utf8" });
    const tool = (dl.stdout || "").trim();
    if (!tool) {
      log("neither curl nor wget found — cannot auto-install. Install Python 3.10+ manually.");
      return false;
    }
    const pipeCmd = tool === "curl"
      ? "curl -LsSf https://astral.sh/uv/install.sh | sh"
      : "wget -qO- https://astral.sh/uv/install.sh | sh";
    r = spawnSync("sh", ["-c", pipeCmd], { stdio: ["ignore", "inherit", "inherit"], timeout: 600000 });
  }
  if (!r || r.status !== 0) {
    log("uv installer failed");
    return false;
  }
  return true;
}

function provisionPython() {
  if ((process.env.HARNESS_AUTO_PYTHON || "1") === "0") {
    log("Python 3.10+ not found and HARNESS_AUTO_PYTHON=0 — auto-install disabled.");
    log("Install Python 3.10+ manually: https://www.python.org/downloads/");
    return false;
  }
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  } catch (e) {
    log(`cannot create ${DATA_DIR}: ${e.message}`);
    return false;
  }

  // SIGKILL/강제 종료로 고아가 된 락은 시효(mtime 기준)로 부순다 — 경합 대기 300초의 2배.
  const LOCK_STALE_MS = 600000;
  const lockIsStale = () => {
    try {
      return Date.now() - fs.statSync(LOCK_DIR).mtimeMs > LOCK_STALE_MS;
    } catch (_) {
      return false;
    }
  };
  const tryAcquireLock = () => {
    try { fs.mkdirSync(LOCK_DIR); return true; } catch (_) { /* 보유 중 */ }
    if (lockIsStale()) {
      try { fs.rmdirSync(LOCK_DIR); } catch (_) { /* 경쟁 제거됨 */ }
      try { fs.mkdirSync(LOCK_DIR); return true; } catch (_) { /* 타 프로세스 선점 */ }
    }
    return false;
  };

  if (tryAcquireLock()) {
    const release = () => {
      try {
        fs.rmdirSync(LOCK_DIR);
      } catch (_) {
        /* 이미 정리됨 */
      }
    };
    // 시그널 핸들러는 설치 구간에만 스코프 — 이후 서버 실행(runInherit)의 전달 로직과 충돌 방지.
    const onSigint = () => { release(); process.exit(130); };
    const onSigterm = () => { release(); process.exit(143); };
    process.on("SIGINT", onSigint);
    process.on("SIGTERM", onSigterm);
    try {
      let uv = findUv();
      if (!uv) {
        if (!installUv()) return false;
        uv = findUv();
        if (!uv) {
          log("uv not found after install");
          return false;
        }
      }
      log(`installing managed Python ${UV_PY_VERSION} via uv (one-time download) ...`);
      let r = spawnSync(uv, ["python", "install", UV_PY_VERSION], { stdio: ["ignore", "inherit", "inherit"], timeout: 600000, windowsHide: true });
      if (r.status !== 0) {
        log("'uv python install' failed");
        return false;
      }
      r = spawnSync(uv, ["python", "find", "--managed-python", UV_PY_VERSION], { encoding: "utf8", timeout: 60000, windowsHide: true });
      const p = r.status === 0 ? (r.stdout || "").trim() : "";
      if (!p || !probePython(p, [])) {
        log(`provisioned python is unusable: ${p || "(none)"}`);
        return false;
      }
      fs.writeFileSync(PIN_FILE, `${p}\n`);
      log(`Python ready: ${p}`);
      return true;
    } finally {
      release();
      process.off("SIGINT", onSigint);
      process.off("SIGTERM", onSigterm);
    }
  }

  // 락 경합 — 설치 완료를 최대 300초 대기(run-server.sh와 동일). 시효 초과 락은 부수고 재시도.
  for (let i = 0; i < 300; i++) {
    if (pinnedPython()) return true;
    if (!fs.existsSync(LOCK_DIR)) break;
    if (lockIsStale()) {
      try { fs.rmdirSync(LOCK_DIR); } catch (_) { /* 경쟁 제거됨 */ }
      return provisionPython();
    }
    sleepSync(1000);
  }
  return pinnedPython() !== null;
}

/** 사용자 화면용 수동 폴백 안내 — SessionStart 훅 exit 2 시 stderr가 transcript에 표시된다. */
function printFallback(kind, py) {
  const req = path.join(SCRIPT_DIR, "requirements.txt");
  const lines = ["[test-autoevermation-harness-plugin] MCP 의존성 자동 설치 실패 — 아래 명령으로 수동 설치 후 /reload-plugins 하세요:"];
  if (kind === "python") {
    lines.push("  1) Python 3.10+ 설치: macOS 'brew install python' | Ubuntu/Debian 'sudo apt install python3 python3-venv python3-pip' | Windows 'winget install Python.Python.3.12' | https://www.python.org/downloads/");
    lines.push(`  2) MCP SDK 설치: ${IS_WIN ? "python" : "python3"} -m pip install -r "${req}"`);
    if ((process.env.HARNESS_AUTO_PYTHON || "1") === "0") {
      lines.push("  (참고: HARNESS_AUTO_PYTHON=0 으로 자동 설치가 꺼져 있습니다)");
    }
  } else {
    lines.push(`  MCP SDK 설치: ${IS_WIN ? "python" : "python3"} -m pip install -r "${req}"`);
    lines.push(`  (Python은 준비됨: ${py} — 위 명령은 .mcp.json이 실행하는 동일 인터프리터에 설치해야 합니다)`);
  }
  lines.push("  다음 세션 시작 시 자동 설치를 다시 시도합니다.");
  process.stderr.write(lines.join("\n") + "\n");
}

function resolvePython() {
  let py = findSystemPython();
  if (py) return py;
  py = pinnedPython();
  if (py) return py;
  if (provisionPython()) return pinnedPython();
  return null;
}

/** 자식 프로세스를 stdio 상속으로 실행하고 종료 코드를 그대로 전달한다(MCP stdio 패스스루). */
function runInherit(cmd, args) {
  const child = spawn(cmd, args, { stdio: "inherit", windowsHide: true });
  const forward = (sig) => { try { child.kill(sig); } catch (_) { /* 이미 종료 */ } };
  process.on("SIGINT", () => forward("SIGINT"));
  process.on("SIGTERM", () => forward("SIGTERM"));
  child.on("exit", (code, signal) => process.exit(signal ? 143 : (code == null ? 1 : code)));
  child.on("error", (e) => { log(`failed to launch: ${e.message}`); process.exit(1); });
}

function main() {
  const argv = process.argv.slice(2);
  const bootstrap = path.join(SCRIPT_DIR, "bootstrap.py");

  if (argv[0] === "--ensure-only") {
    const py = resolvePython();
    if (!py) {
      log("Python 3.10+ unavailable and auto-provisioning failed — MCP servers cannot start.");
      printFallback("python");
      process.exit(2);
    }
    const r = spawnSync(py, [bootstrap, "--ensure-only"], { stdio: "inherit", windowsHide: true });
    if (r.status === 0) process.exit(0);
    printFallback("deps", py);
    process.exit(2);
  }

  if (argv[0] === "script") {
    // 훅/statusline 경로 — stdlib 전용 스크립트라 venv 불필요. Python 미해결이어도
    // 훅 전체를 깨뜨리지 않도록 fail-open(안내는 SessionStart 훅이 담당).
    const scriptPath = argv[1];
    if (!scriptPath) {
      log("usage: launch.cjs script <script.py> [args...]");
      process.exit(0);
    }
    const py = findSystemPython() || pinnedPython();
    if (!py) {
      log(`Python unavailable — skipping ${path.basename(scriptPath)} (fail-open).`);
      process.exit(0);
    }
    runInherit(py, [scriptPath, ...argv.slice(2)]);
    return;
  }

  if (!argv[0]) {
    log("usage: launch.cjs <server.py> [args...] | --ensure-only | script <script.py> [args...]");
    process.exit(1);
  }

  const py = resolvePython();
  if (!py) {
    log("Python 3.10+ unavailable and auto-provisioning failed — MCP servers cannot start.");
    log("Manual fix: install Python 3.10+ (brew/apt/winget/python.org), then /reload-plugins.");
    process.exit(1);
  }
  runInherit(py, [bootstrap, ...argv]);
}

main();
