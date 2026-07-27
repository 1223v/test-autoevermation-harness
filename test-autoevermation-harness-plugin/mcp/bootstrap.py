#!/usr/bin/env python3
"""MCP 의존성 자동 부트스트랩.

플러그인 설치 직후 사용자가 아무것도 설치하지 않아도 MCP 서버 3개가 뜨도록,
공식 권장 패턴(plugins-reference의 ${CLAUDE_PLUGIN_DATA} + SessionStart 훅)으로
`mcp[cli]`를 플러그인 전용 venv에 1회 설치하고 그 인터프리터로 서버를 실행한다.

사용 형태:
  python3 bootstrap.py <server.py> [args...]  # .mcp.json 경유 — 의존성 보장 후 서버로 exec
  python3 bootstrap.py --ensure-only          # SessionStart 훅 경유 — venv만 준비하고 종료

동작 규칙:
- 현재 인터프리터가 이미 `mcp`를 임포트할 수 있으면 venv 없이 그대로 실행(기존 환경 존중).
- venv 위치: $CLAUDE_PLUGIN_DATA/venv (업데이트에도 유지). 변수 미주입 환경(로컬 dev 등)은
  <plugin>/mcp/.plugin-data/venv 로 폴백.
- requirements.txt 사본을 marker로 저장해 두고, 번들 파일과 다르면(첫 실행/의존성 변경 업데이트)
  재설치한다 — 공식 문서의 diff-manifest 패턴과 동일.
- 서버 3개가 동시에 기동하며 경쟁하므로 flock으로 설치를 직렬화한다.
- 설치 중 첫 세션에서 MCP 연결 타임아웃(30s)이 나더라도 설치는 marker 기준으로 이어지고,
  SessionStart 훅/다음 reload에서 정상화된다.

stdlib 전용 — 이 스크립트 자체는 어떤 서드파티 패키지도 요구하지 않는다.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(SCRIPT_DIR, "requirements.txt")
MIN_PY = (3, 10)  # mcp[cli] 요구(공식 MCP Python SDK: Python 3.10+)


def log(msg):
    # stderr는 Claude Code가 MCP 로그(mcp-logs-*)로 수집한다.
    print("test-autoevermation-harness-plugin bootstrap: %s" % msg, file=sys.stderr)


def data_dir():
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not d:
        # 로컬 dev(--plugin-dir 미사용 상황 등) 폴백 — 플러그인 루트 안이라 업데이트 시 초기화됨
        d = os.path.join(SCRIPT_DIR, ".plugin-data")
    return d


def venv_python(venv_dir):
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python3")


def current_interpreter_has_mcp():
    try:
        import importlib.util

        return importlib.util.find_spec("mcp") is not None
    except Exception:
        return False


def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def plugin_version():
    """플러그인 선언 버전(best-effort). 실패 시 'unknown' — 예외 없음."""
    try:
        import json

        manifest = os.path.join(
            os.path.dirname(SCRIPT_DIR), ".claude-plugin", "plugin.json"
        )
        with open(manifest, encoding="utf-8") as f:
            return str(json.load(f).get("version") or "unknown")
    except Exception:
        return "unknown"


def marker_payload():
    """설치 마커의 기대 내용: requirements 원문 + 플러그인 버전 스탬프.

    버전을 접어 넣는 이유: 플러그인 업데이트 후 첫 SessionStart에서 의존성
    재검증(pip install -r — 충족 시 빠른 no-op)을 강제해, requirements가
    바뀌지 않아도 venv 상태가 새 버전 기준으로 한 번은 확인되게 한다.
    """
    bundled = read_file(REQUIREMENTS)
    if bundled is None:
        return None
    return bundled + "\n# plugin-version: %s\n" % plugin_version()


def deps_ready(marker_path):
    expected = marker_payload()
    installed = read_file(marker_path)
    return expected is not None and expected == installed


class InstallLock:
    """flock 기반 설치 직렬화. flock 불가 환경은 잠금 없이 진행(pip 자체가 재실행 안전)."""

    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.fd = None

    def __enter__(self):
        try:
            import fcntl

            self.fd = open(self.lock_path, "w")
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except Exception:
            self.fd = None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                self.fd.close()
            except Exception:
                pass
        return False


def ensure_venv():
    """venv를 준비하고 사용할 파이썬 실행 파일 경로를 돌려준다. 실패 시 None."""
    if sys.version_info < MIN_PY:
        log(
            "Python %d.%d+ required by mcp[cli], but running %s"
            % (MIN_PY[0], MIN_PY[1], sys.version.split()[0])
        )
        return None

    base = data_dir()
    venv_dir = os.path.join(base, "venv")
    py = venv_python(venv_dir)
    marker = os.path.join(base, "requirements.installed.txt")

    if os.path.exists(py) and deps_ready(marker):
        return py

    try:
        os.makedirs(base, exist_ok=True)
    except Exception as e:
        log("cannot create data dir %s: %s" % (base, e))
        return None
    with InstallLock(os.path.join(base, ".bootstrap.lock")):
        # 잠금 대기 중 다른 서버 프로세스가 설치를 끝냈을 수 있다
        if os.path.exists(py) and deps_ready(marker):
            return py

        if not os.path.exists(py):
            log("creating venv at %s" % venv_dir)
            r = subprocess.run(
                [sys.executable, "-m", "venv", venv_dir],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                log("venv creation failed: %s" % (r.stderr or r.stdout).strip())
                return None

        log("installing MCP dependencies (first run only) ...")
        r = subprocess.run(
            [py, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log("pip install failed: %s" % (r.stderr or r.stdout).strip()[-2000:])
            return None

        payload = marker_payload() or ""
        with open(marker, "w", encoding="utf-8") as f:
            f.write(payload)
        log("dependencies ready at %s" % venv_dir)
        return py


def main():
    args = sys.argv[1:]
    ensure_only = args and args[0] == "--ensure-only"

    if current_interpreter_has_mcp():
        py = sys.executable
        # 시스템 인터프리터에 mcp가 이미 있으면 venv를 우회한다(기존 환경 존중).
        # 이 경로는 requirements/버전 마커의 추적을 받지 않으므로, 시스템 mcp가
        # 낡아도 감지되지 않는다 — 진단 가능하도록 소리 내어 기록한다.
        log(
            "system interpreter already imports 'mcp' — plugin venv BYPASSED "
            "(%s); dependency drift is not tracked on this path" % py
        )
    else:
        py = ensure_venv()

    if ensure_only:
        # 실패 시 exit 1 — 호출자(run-server.sh)가 SessionStart exit 2 + stderr로
        # 변환해 사용자 화면에 수동 폴백 명령을 표시한다(세션은 계속 진행됨)
        if py is None:
            log("dependency provisioning failed; MCP servers will be unavailable")
            return 1
        return 0

    if not args:
        log("usage: bootstrap.py <server.py> [args...] | --ensure-only")
        return 1

    if py is None:
        log(
            "cannot provision 'mcp' package automatically. Manual fallback: "
            "python3 -m pip install -r \"%s\"" % REQUIREMENTS
        )
        return 1

    server = args[0]
    argv = [py, server] + args[1:]

    if os.name == "nt":
        # Windows의 exec*는 프로세스를 대체하지 않는다 — CPython은 이를
        # spawnv(P_NOWAIT) + _exit(0)으로 구현하므로(공식 os 문서, cpython#101191)
        # execv를 쓰면 이 프로세스가 즉시 끝난다. .mcp.json의 기동 체인은
        # Claude Code → node launch.cjs(runInherit: 자식이 끝나면 자신도 exit)
        # → python bootstrap → 서버 이므로, bootstrap이 먼저 끝나면 node도 끝나고
        # MCP stdio 연결이 그 자리에서 죽는다. 서버가 살아 있어도 파이프가 끊긴다.
        # 따라서 Windows에서는 자식을 stdio 상속으로 돌리고 끝까지 기다린다.
        return subprocess.run(argv).returncode

    os.execv(py, argv)
    return 1  # execv 성공 시 도달 불가


if __name__ == "__main__":
    sys.exit(main())
