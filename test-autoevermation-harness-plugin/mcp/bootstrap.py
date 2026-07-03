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


def deps_ready(marker_path):
    bundled = read_file(REQUIREMENTS)
    installed = read_file(marker_path)
    return bundled is not None and bundled == installed


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

    os.makedirs(base, exist_ok=True)
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

        bundled = read_file(REQUIREMENTS) or ""
        with open(marker, "w", encoding="utf-8") as f:
            f.write(bundled)
        log("dependencies ready at %s" % venv_dir)
        return py


def main():
    args = sys.argv[1:]
    ensure_only = args and args[0] == "--ensure-only"

    if current_interpreter_has_mcp():
        py = sys.executable
    else:
        py = ensure_venv()

    if ensure_only:
        # SessionStart 훅: 세션을 막지 않도록 항상 0으로 종료(실패는 stderr 진단만)
        if py is None:
            log("dependency provisioning failed; MCP servers will be unavailable")
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
    os.execv(py, [py, server] + args[1:])
    return 1  # execv 성공 시 도달 불가


if __name__ == "__main__":
    sys.exit(main())
