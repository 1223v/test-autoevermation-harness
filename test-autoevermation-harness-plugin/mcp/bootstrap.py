#!/usr/bin/env python3
"""MCP 의존성 자동 부트스트랩.

플러그인 설치 직후 사용자가 아무것도 설치하지 않아도 MCP 서버 3개가 뜨도록,
공식 권장 패턴(plugins-reference의 ${CLAUDE_PLUGIN_DATA} + SessionStart 훅)으로
`mcp[cli]`를 플러그인 전용 venv에 1회 설치하고 그 인터프리터로 서버를 실행한다.

사용 형태:
  python3 bootstrap.py <server.py> [args...]  # .mcp.json 경유 — 의존성 보장 후 서버로 exec
  python3 bootstrap.py --ensure-only          # SessionStart 훅 경유 — venv만 준비하고 종료

동작 규칙:
- 현재 인터프리터의 SDK >=2.2,<3 버전과 MCPServer 실제 import가 검증되면 venv 없이 그대로 실행(기존 환경 존중).
- venv 위치: $CLAUDE_PLUGIN_DATA/venv (업데이트에도 유지). 변수 미주입 환경(로컬 dev 등)은
  <plugin>/mcp/.plugin-data/venv 로 폴백.
- requirements.txt 사본을 marker로 저장해 두고, 번들 파일과 다르면(첫 실행/의존성 변경 업데이트)
  재설치한다 — 공식 문서의 diff-manifest 패턴과 동일.
- 서버 3개가 동시에 기동하며 경쟁하므로 OS 파일 잠금(flock/msvcrt)으로 설치를 직렬화한다.
- 설치 중 첫 세션에서 MCP 연결 타임아웃(30s)이 나더라도 설치는 marker 기준으로 이어지고,
  SessionStart 훅/다음 reload에서 정상화된다.

stdlib 전용 — 이 스크립트 자체는 어떤 서드파티 패키지도 요구하지 않는다.
"""

import os
import re
import tempfile
import time
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(SCRIPT_DIR, "requirements.txt")
MIN_PY = (3, 10)  # mcp[cli] 요구(공식 MCP Python SDK: Python 3.10+)


def log(msg):
    # stderr는 Claude Code가 MCP 로그(mcp-logs-*)로 수집한다.
    print("test-autoevermation-harness-plugin bootstrap: %s" % msg, file=sys.stderr)


def data_dir():
    key = "PLUGIN_DATA" if os.environ.get("HARNESS_HOST") == "codex" else "CLAUDE_PLUGIN_DATA"
    d = os.environ.get(key) or os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not d:
        # 로컬 dev(--plugin-dir 미사용 상황 등) 폴백 — 플러그인 루트 안이라 업데이트 시 초기화됨
        d = os.path.join(SCRIPT_DIR, ".plugin-data")
    return d


def venv_python(venv_dir):
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python3")


def current_interpreter_has_mcp():
    """Both the supported SDK version AND its actual public server API must load."""
    try:
        from importlib.metadata import version
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.post\d+)?", version("mcp"))
        if not match or not (2, 2, 0) <= tuple(map(int, match.groups())) < (3, 0, 0):
            return False
        from mcp.server.mcpserver import MCPServer
        return callable(MCPServer)
    except Exception:
        return False


def interpreter_has_mcp(python):
    try:
        probe = ("import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                 "sys.exit(0 if m['current_interpreter_has_mcp']() else 1)")
        result = subprocess.run([python, "-c", probe, os.path.abspath(__file__)],
                                capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
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


def deps_ready(marker_path, python=None):
    expected = marker_payload()
    installed = read_file(marker_path)
    return (expected is not None and expected == installed
            and (python is None or interpreter_has_mcp(python)))


class InstallLock:
    """Process lock released by the OS after crashes; never silently skip locking."""
    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.fd = None

    def __enter__(self):
        self.fd = open(self.lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.fd.tell() == 0:
                    self.fd.write(b"0"); self.fd.flush()
                self.fd.seek(0)
                deadline = time.monotonic() + 600
                while True:
                    try:
                        msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("MCP install lock timed out")
                        time.sleep(.1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX)
        except BaseException:
            self.fd.close()
            raise
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            if os.name == "nt":
                import msvcrt
                self.fd.seek(0)
                msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
            self.fd.close()
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

    if os.path.exists(py) and deps_ready(marker, py):
        return py

    try:
        os.makedirs(base, exist_ok=True)
    except Exception as e:
        log("cannot create data dir %s: %s" % (base, e))
        return None
    with InstallLock(os.path.join(base, ".bootstrap.lock")):
        # 잠금 대기 중 다른 서버 프로세스가 설치를 끝냈을 수 있다
        if os.path.exists(py) and deps_ready(marker, py):
            return py

        # Invalidate before any repair; failed provisioning cannot leave a ready marker.
        try:
            os.unlink(marker)
        except FileNotFoundError:
            pass
        pip_ready = False
        if os.path.exists(py):
            try:
                pip_ready = subprocess.run(
                    [py, "-m", "pip", "--version"], capture_output=True,
                    text=True, timeout=30,
                ).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not pip_ready:
            # Only rebuild the plugin-owned directory, never a symlink target.
            if os.path.islink(venv_dir):
                log("refusing to rebuild a symlinked venv; provide a real plugin data directory")
                return None
            log("creating/repairing venv at %s" % venv_dir)
            command = [sys.executable, "-m", "venv"]
            if os.path.isdir(venv_dir):
                command.append("--clear")
            r = subprocess.run(command + [venv_dir], capture_output=True, text=True)
            if r.returncode != 0:
                log("venv creation failed: %s" % (r.stderr or r.stdout).strip())
                return None

        log("installing/verifying MCP SDK 2.x dependencies ...")
        r = subprocess.run(
            [py, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log("pip install failed: %s" % (r.stderr or r.stdout).strip()[-2000:])
            return None

        if not interpreter_has_mcp(py):
            log("installed SDK does not satisfy >=2.2,<3 or MCPServer import failed")
            return None
        payload = marker_payload()
        if payload is None:
            return None
        fd, temporary = tempfile.mkstemp(prefix=".requirements-", dir=base)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, marker)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        log("dependencies ready at %s" % venv_dir)
        return py


def main():
    args = sys.argv[1:]
    ensure_only = args and args[0] == "--ensure-only"

    if current_interpreter_has_mcp():
        py = sys.executable
        log("system interpreter verified: MCP SDK >=2.2,<3 and MCPServer import (%s)" % py)
    else:
        try:
            py = ensure_venv()
        except (OSError, subprocess.SubprocessError) as exc:
            log("provisioning failed: %s" % exc)
            py = None

    if ensure_only:
        # 실패 시 exit 1 — 호출자(launch.cjs --ensure-only; POSIX 수동 폴백 run-server.sh)가 SessionStart exit 2 + stderr로
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
