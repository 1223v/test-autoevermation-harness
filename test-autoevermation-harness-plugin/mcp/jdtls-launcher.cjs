#!/usr/bin/env node
/* jdtls-launcher.cjs — 크로스플랫폼 JDT LS 진입점 (Windows 네이티브 + macOS/Linux).
 *
 * .lsp.json은 exec form(`command: "node"` + args)으로 이 파일을 실행한다.
 * launch.cjs와 동일하게 셸을 거치지 않고 실제 바이너리를 직접 spawn하므로 모든 플랫폼에서 동작한다.
 *
 * 사용:
 *   node jdtls-launcher.cjs [jdtls-args...]   # .lsp.json — jdtls를 해석해 argv 그대로 전달
 *
 * 동작:
 * 1) PATH의 `jdtls`(POSIX) / `jdtls.bat`(Windows)를 우선 존중.
 * 2) 없으면 provision된 사본 `${CLAUDE_PLUGIN_DATA||<mcp>/.plugin-data}/jdtls/bin/jdtls[.bat]` 사용
 *    (setup_jdtls.py가 설치하는 위치 — launch.cjs/bootstrap.py와 동일한 데이터 디렉터리 규칙).
 * 3) 둘 다 없으면 stderr에 setup_jdtls.py 실행 안내를 출력하고 exit 1.
 *
 * 해석된 jdtls는 stdio 상속으로 실행하고 종료 코드를 그대로 전달한다(LSP stdio 패스스루).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const IS_WIN = process.platform === "win32";
const SCRIPT_DIR = __dirname;
const PLUGIN_ROOT = path.dirname(SCRIPT_DIR);
const DATA_DIR = process.env.CLAUDE_PLUGIN_DATA || path.join(SCRIPT_DIR, ".plugin-data");

function log(msg) {
  process.stderr.write(`test-autoevermation-harness-plugin jdtls-launcher: ${msg}\n`);
}

function jdtlsBinName() {
  return IS_WIN ? "jdtls.bat" : "jdtls";
}

/** PATH에서 jdtls를 찾는다(존재/실행 가능하면 명령 이름을 반환, 아니면 null). */
function jdtlsOnPath() {
  const name = jdtlsBinName();
  try {
    // where(Windows)/command -v(POSIX)로 PATH 해석 여부만 확인.
    const probe = IS_WIN
      ? spawnSync("where", [name], { encoding: "utf8", timeout: 15000, windowsHide: true })
      : spawnSync("sh", ["-c", `command -v ${name}`], { encoding: "utf8", timeout: 15000 });
    if (probe.status === 0 && (probe.stdout || "").trim()) return name;
  } catch (_) {
    /* PATH에 없음 */
  }
  return null;
}

/** provision된 사본 경로를 반환(파일 존재 시), 아니면 null. */
function provisionedJdtls() {
  const bin = path.join(DATA_DIR, "jdtls", "bin", jdtlsBinName());
  return fs.existsSync(bin) ? bin : null;
}

function resolveJdtls() {
  return jdtlsOnPath() || provisionedJdtls();
}

/** 자식 프로세스를 stdio 상속으로 실행하고 종료 코드를 그대로 전달한다(LSP stdio 패스스루). */
function runInherit(cmd, args) {
  const child = spawn(cmd, args, { stdio: "inherit", windowsHide: true });
  const forward = (sig) => { try { child.kill(sig); } catch (_) { /* 이미 종료 */ } };
  process.on("SIGINT", () => forward("SIGINT"));
  process.on("SIGTERM", () => forward("SIGTERM"));
  child.on("exit", (code, signal) => process.exit(signal ? 143 : (code == null ? 1 : code)));
  child.on("error", (e) => { log(`failed to launch jdtls: ${e.message}`); process.exit(1); });
}

function main() {
  const argv = process.argv.slice(2);
  const jdtls = resolveJdtls();
  if (!jdtls) {
    const setup = path.join(PLUGIN_ROOT, "scripts", "setup_jdtls.py");
    const launch = path.join(SCRIPT_DIR, "launch.cjs");
    log("jdtls not found on PATH or under the plugin data dir.");
    log(`Provision it with: node ${launch} script ${setup}`);
    log("(installs a pinned Eclipse JDT LS milestone; requires a JDK 21+ on PATH or JAVA_HOME).");
    process.exit(1);
  }
  runInherit(jdtls, argv);
}

main();
