#!/usr/bin/env node
/* TAM statusline 전용 독립 런처 — 플러그인 디렉터리에 의존하지 않는다.
 *
 * 이 파일은 setup 시 `${CLAUDE_CONFIG_DIR:-~/.claude}/`로 복사되고, settings.json의
 * `statusLine.command`가 `node "<이 파일>"`로 이를 가리킨다. 플러그인이 uninstall되어
 * 캐시 디렉터리가 삭제돼도 이 런처와 sibling wrapper(.py)/config(.json)는 전역 설정
 * 디렉터리에 남아 계속 실행된다 → wrapper가 self-heal로 원래 상태줄을 원복한다.
 *
 * 크로스플랫폼 파이썬 해석은 mcp/launch.cjs의 방식을 미러링한다(POSIX: python3…,
 * Windows: py -3 → python). 파이썬이 없거나 wrapper .py가 없으면 config의 delegate를
 * 직접 실행해 기존 상태줄(예: OMC HUD)이 깨지지 않도록 한다. 항상 exit 0.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const IS_WIN = process.platform === "win32";
const HERE = __dirname;
const WRAPPER_PY = path.join(HERE, "test-autoevermation-statusline.py");
const CONFIG_JSON = path.join(HERE, "test-autoevermation-statusline.json");

function readStdin() {
  try {
    return fs.readFileSync(0);
  } catch (_) {
    return Buffer.alloc(0);
  }
}

/** 후보 파이썬이 3.8+이면 그 커맨드+선행인자를 돌려준다. */
function findPython() {
  const candidates = IS_WIN
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  const check = "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)";
  for (const [cmd, pre] of candidates) {
    try {
      const r = spawnSync(cmd, [...pre, "-c", check], {
        timeout: 15000,
        windowsHide: true,
      });
      if (r.status === 0) return [cmd, pre];
    } catch (_) {
      /* 다음 후보 */
    }
  }
  return null;
}

/** wrapper .py가 없거나 파이썬이 없을 때: config.delegate만 실행해 기존 상태줄 유지. */
function runDelegateOnly(stdin) {
  let delegate = null;
  try {
    delegate = JSON.parse(fs.readFileSync(CONFIG_JSON, "utf8")).delegate;
  } catch (_) {
    delegate = null;
  }
  if (!delegate) return; // 원래 상태줄이 없었음 — 아무것도 출력하지 않음
  const shell = IS_WIN
    ? [process.env.COMSPEC || "cmd.exe", ["/c", delegate]]
    : ["/bin/sh", ["-c", delegate]];
  try {
    const r = spawnSync(shell[0], shell[1], {
      input: stdin,
      timeout: 8000,
      windowsHide: true,
    });
    if (r.stdout) process.stdout.write(r.stdout);
  } catch (_) {
    /* 상태줄은 조용히 실패 */
  }
}

function main() {
  const py = fs.existsSync(WRAPPER_PY) ? findPython() : null;
  if (py) {
    // wrapper가 stdin(JSON)을 직접 읽고 stdout에 직접 쓴다 — 그대로 통과.
    const r = spawnSync(py[0], [...py[1], WRAPPER_PY], {
      stdio: "inherit",
      windowsHide: true,
    });
    if (r.status === 0 || r.status === null) return 0;
    // wrapper가 비정상 종료하면 delegate 폴백으로 최소한 기존 상태줄은 유지.
  }
  runDelegateOnly(readStdin());
  return 0;
}

process.exit(main());
