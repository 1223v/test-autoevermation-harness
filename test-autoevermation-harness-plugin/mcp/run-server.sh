#!/bin/sh
# MCP 진입점 — Python이 아예 없는 PC에서도 동작해야 하므로 POSIX sh로 작성.
#
# 사용:
#   run-server.sh <server.py> [args...]   # .mcp.json 경유 — Python+의존성 보장 후 bootstrap.py로 exec
#   run-server.sh --ensure-only           # SessionStart 훅 경유 — Python+의존성만 준비하고 종료
#
# 동작:
# 1) PATH에서 Python 3.10+를 찾으면 그대로 사용(기존 환경 존중).
# 2) 없으면 uv(공식 standalone installer, sudo 불필요, ~/.local/bin)로 관리형
#    Python을 1회 자동 설치하고 경로를 ${CLAUDE_PLUGIN_DATA}/python-path에 고정.
#    비활성화: HARNESS_AUTO_PYTHON=0 (수동 설치 안내만 출력).
# 3) 동시 기동(서버 3개+훅) 경쟁은 mkdir 락으로 직렬화(macOS에 flock 바이너리 없음).
# 근거: uv 공식 문서 — install.sh는 ~/.local/bin에 무-sudo 설치,
#       `uv python install`/`uv python find --managed-python`은 사용자 홈에 관리형 설치.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_DIR=${CLAUDE_PLUGIN_DATA:-$SCRIPT_DIR/.plugin-data}
PIN_FILE="$DATA_DIR/python-path"
LOCK_DIR="$DATA_DIR/.python-install.lock"
MIN_CHECK='import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
UV_PY_VERSION=3.12

log() { echo "test-autoevermation-harness-plugin run-server: $*" >&2; }

usable() { [ -n "$1" ] && [ -x "$1" ] && "$1" -c "$MIN_CHECK" >/dev/null 2>&1; }

find_system_python() {
  for c in python3 python3.13 python3.12 python3.11 python3.10; do
    p=$(command -v "$c" 2>/dev/null) || continue
    if usable "$p"; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}

find_uv() {
  # 방금 설치한 직후엔 ~/.local/bin이 PATH에 없을 수 있어 명시 경로도 확인
  for u in uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    p=$(command -v "$u" 2>/dev/null) || p="$u"
    if [ -x "$p" ]; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}

pinned_python() {
  [ -f "$PIN_FILE" ] || return 1
  p=$(cat "$PIN_FILE" 2>/dev/null)
  usable "$p" || return 1
  printf '%s\n' "$p"
}

provision_python() {
  if [ "${HARNESS_AUTO_PYTHON:-1}" = "0" ]; then
    log "Python 3.10+ not found and HARNESS_AUTO_PYTHON=0 — auto-install disabled."
    log "Install Python 3.10+ manually: https://www.python.org/downloads/"
    return 1
  fi
  mkdir -p "$DATA_DIR" 2>/dev/null || { log "cannot create $DATA_DIR"; return 1; }

  if mkdir "$LOCK_DIR" 2>/dev/null; then
    # 락 획득 — 실패로 스크립트가 죽어도 락이 남지 않도록 EXIT에서 정리
    trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT INT TERM
    if ! UV=$(find_uv); then
      log "installing uv (user-local, no sudo; https://astral.sh/uv) ..."
      if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >&2 || { log "uv installer failed"; return 1; }
      elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh >&2 || { log "uv installer failed"; return 1; }
      else
        log "neither curl nor wget found — cannot auto-install. Install Python 3.10+ manually."
        return 1
      fi
      UV=$(find_uv) || { log "uv not found after install"; return 1; }
    fi
    log "installing managed Python $UV_PY_VERSION via uv (one-time download) ..."
    "$UV" python install "$UV_PY_VERSION" >&2 || { log "'uv python install' failed"; return 1; }
    p=$("$UV" python find --managed-python "$UV_PY_VERSION" 2>/dev/null) || { log "'uv python find' failed"; return 1; }
    usable "$p" || { log "provisioned python is unusable: $p"; return 1; }
    printf '%s\n' "$p" > "$PIN_FILE"
    log "Python ready: $p"
    return 0
  fi

  # 락 경합 — 다른 프로세스(동시 기동한 서버/훅)가 설치 중이므로 완료를 대기
  i=0
  while [ "$i" -lt 300 ]; do
    if pinned_python >/dev/null; then return 0; fi
    [ -d "$LOCK_DIR" ] || break
    sleep 1
    i=$((i + 1))
  done
  pinned_python >/dev/null
}

# 사용자 화면용 수동 폴백 안내. SessionStart 훅(--ensure-only)에서 exit 2로 끝나면
# stderr가 세션 transcript에 그대로 표시된다(공식 hooks 문서 — 세션은 계속 진행).
print_fallback() {
  {
    echo "[test-autoevermation-harness-plugin] MCP 의존성 자동 설치 실패 — 아래 명령으로 수동 설치 후 /reload-plugins 하세요:"
    if [ "$1" = "python" ]; then
      echo "  1) Python 3.10+ 설치: macOS 'brew install python' | Ubuntu/Debian 'sudo apt install python3 python3-venv python3-pip' | https://www.python.org/downloads/"
      echo "  2) MCP SDK 설치: python3 -m pip install -r \"$SCRIPT_DIR/requirements.txt\""
      [ "${HARNESS_AUTO_PYTHON:-1}" = "0" ] && echo "  (참고: HARNESS_AUTO_PYTHON=0 으로 자동 설치가 꺼져 있습니다)"
    else
      echo "  MCP SDK 설치: python3 -m pip install -r \"$SCRIPT_DIR/requirements.txt\""
      echo "  (Python은 준비됨: $PY — 위 명령은 .mcp.json이 실행하는 동일 인터프리터에 설치해야 합니다)"
    fi
    echo "  다음 세션 시작 시 자동 설치를 다시 시도합니다."
  } >&2
}

ENSURE_ONLY=0
[ "${1:-}" = "--ensure-only" ] && ENSURE_ONLY=1

if PY=$(find_system_python); then
  :
elif PY=$(pinned_python); then
  :
elif provision_python; then
  PY=$(pinned_python) || { log "python pin missing after provisioning"; exit 1; }
else
  log "Python 3.10+ unavailable and auto-provisioning failed — MCP servers cannot start."
  if [ "$ENSURE_ONLY" = "1" ]; then
    print_fallback python
    exit 2
  fi
  log "Manual fix: install Python 3.10+ (brew/apt/python.org), then /reload-plugins."
  exit 1
fi

if [ "$ENSURE_ONLY" = "1" ]; then
  if "$PY" "$SCRIPT_DIR/bootstrap.py" --ensure-only; then
    exit 0
  fi
  print_fallback deps
  exit 2
fi

exec "$PY" "$SCRIPT_DIR/bootstrap.py" "$@"
