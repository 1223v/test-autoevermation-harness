#!/usr/bin/env python3
"""TAM statusline 자동 설정 — SessionStart 훅 + 설치/해제 서브커맨드.

Claude Code 플러그인은 install/uninstall 라이프사이클 훅이 없다(공식 문서 확인).
그래서 "설치 시 자동 세팅"은 SessionStart 훅으로, "제거 시 자동 원복"은 전역 사본
wrapper의 self-heal로 나눠 구현한다. 이 스크립트는 전자(설치·갱신·재점유)와
사용자 승인 기록, 그리고 수동 제거를 담당한다.

전역 상태줄(main statusLine)은 플러그인 자체 settings로는 설정할 수 없으므로
(공식: plugin settings는 agent/subagentStatusLine만 적용) 사용자 전역
`${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`을 직접(JSON 라운드트립) 편집한다.
TAM이 top-level statusLine을 소유하고, 기존 커맨드(예: OMC HUD)는 delegate로 보존해
전역 런처가 계속 실행한다. OMC 등이 상태줄을 되가져가면 다음 SessionStart에서 재점유한다.

서브커맨드:
  (없음)                          SessionStart 훅. stdin의 source로 동작을 가른다.
  --install --consent granted     설치/갱신 + consent=granted 기록.
  --install --consent declined    설치 안 함 + consent=declined 기록(자동 설치 영구 opt-out).
  --uninstall                     수동 제거: 원래 상태줄로 원복 + consent=declined.
  --status                        현재 상태를 JSON으로 출력(디버그/스킬용).

항상 exit 0(상태줄/세션 시작을 깨지 않음). kill switch: 환경변수 TAM_STATUSLINE_AUTO=0.
"""

import json
import os
import shutil
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HOOK_DIR)
SRC_WRAPPER = os.path.join(PLUGIN_ROOT, "scripts", "test-autoevermation-statusline.py")
SRC_LAUNCHER = os.path.join(PLUGIN_ROOT, "scripts", "test-autoevermation-statusline-launch.cjs")

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
CONFIG_PATH = os.path.join(CONFIG_DIR, "test-autoevermation-statusline.json")
GLOBAL_WRAPPER = os.path.join(CONFIG_DIR, "test-autoevermation-statusline.py")
GLOBAL_LAUNCHER = os.path.join(CONFIG_DIR, "test-autoevermation-statusline-launch.cjs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
INSTALLED_PLUGINS = os.path.join(CONFIG_DIR, "plugins", "installed_plugins.json")

PLUGIN_KEY_PREFIX = "test-autoevermation-harness-plugin@"
OWNER_MARK = "test-autoevermation-statusline"
SCHEMA_VERSION = 2


# ─────────────────────────── 저수준 IO ───────────────────────────

def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _atomic_write_json(path, data):
    tmp = path + ".tam-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def load_config():
    return _load_json(CONFIG_PATH)


def save_config(cfg):
    _atomic_write_json(CONFIG_PATH, cfg)


def statusline_command():
    """settings.json의 현재 statusLine.command 문자열(없으면 "")."""
    s = _load_json(SETTINGS_PATH)
    if isinstance(s, dict):
        sl = s.get("statusLine")
        if isinstance(sl, dict):
            return sl.get("command", "") or ""
    return ""


def resolve_install_path():
    """uninstall 감지용 경로. 레지스트리의 installPath(캐시 dir)를 우선, 없으면 pluginRoot."""
    reg = _load_json(INSTALLED_PLUGINS)
    if isinstance(reg, dict):
        for key, val in reg.items():
            if key.startswith(PLUGIN_KEY_PREFIX):
                entries = val if isinstance(val, list) else [val]
                for e in entries:
                    if isinstance(e, dict) and e.get("installPath"):
                        return e["installPath"]
    return PLUGIN_ROOT


def launcher_command():
    return 'node "%s"' % GLOBAL_LAUNCHER


# ─────────────────────────── 설치 / 갱신 ───────────────────────────

def copy_global_files():
    """플러그인 → 전역으로 wrapper/launcher를 복사(갱신). 업그레이드 시 경로 드리프트 해소."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    shutil.copyfile(SRC_WRAPPER, GLOBAL_WRAPPER)
    shutil.copyfile(SRC_LAUNCHER, GLOBAL_LAUNCHER)


def do_install(consent="granted"):
    """전역 파일 복사 + settings.json statusLine 점유(멱등). 기존 non-TAM 커맨드는
    delegate로 포획(이중 래핑 금지). 변경이 없으면 settings.json은 건드리지 않는다."""
    if not (os.path.isfile(SRC_WRAPPER) and os.path.isfile(SRC_LAUNCHER)):
        return {"ok": False, "reason": "source files missing", "pluginRoot": PLUGIN_ROOT}

    copy_global_files()

    existing = load_config() or {}
    current_cmd = statusline_command()
    new_cmd = launcher_command()

    # delegate 결정: 현재 커맨드가 이미 우리 것이면 기존 delegate 유지, 아니면 포획.
    if OWNER_MARK in current_cmd:
        delegate = existing.get("delegate")
    else:
        delegate = current_cmd or None

    # settings.json 편집(변경이 있을 때만).
    settings = _load_json(SETTINGS_PATH)
    if not isinstance(settings, dict):
        settings = {}
    sl = settings.get("statusLine")
    already = isinstance(sl, dict) and sl.get("command") == new_cmd
    if not already:
        # non-TAM 상태줄을 처음 대체할 때 1회 백업.
        if OWNER_MARK not in current_cmd and os.path.isfile(SETTINGS_PATH):
            backup = "%s.test-autoevermation-backup-%s" % (
                SETTINGS_PATH, time.strftime("%Y%m%d_%H%M%S"))
            try:
                if not os.path.exists(backup):
                    shutil.copyfile(SETTINGS_PATH, backup)
            except Exception:
                pass
        settings["statusLine"] = {"type": "command", "command": new_cmd}
        _atomic_write_json(SETTINGS_PATH, settings)

    cfg = {
        "delegate": delegate,
        "pluginRoot": PLUGIN_ROOT,
        "installPath": resolve_install_path(),
        "consent": consent,
        "schemaVersion": SCHEMA_VERSION,
        "cleaned": False,
    }
    save_config(cfg)
    return {"ok": True, "changed": not already, "delegate": delegate,
            "command": new_cmd, "consent": consent}


def do_declined():
    """설치하지 않고 consent=declined만 기록(자동 설치 영구 opt-out)."""
    cfg = load_config() or {}
    cfg.update({
        "consent": "declined",
        "pluginRoot": PLUGIN_ROOT,
        "installPath": cfg.get("installPath") or resolve_install_path(),
        "schemaVersion": SCHEMA_VERSION,
        "cleaned": cfg.get("cleaned", False),
    })
    cfg.setdefault("delegate", None)
    save_config(cfg)
    return {"ok": True, "consent": "declined"}


def do_uninstall():
    """수동 제거: statusLine을 delegate로 원복 + 전역 파일 삭제 + consent=declined."""
    cfg = load_config() or {}
    delegate = cfg.get("delegate")

    settings = _load_json(SETTINGS_PATH)
    restored = False
    if isinstance(settings, dict):
        sl = settings.get("statusLine")
        cmd = sl.get("command", "") if isinstance(sl, dict) else ""
        if OWNER_MARK in cmd:
            if delegate:
                settings["statusLine"] = {"type": "command", "command": delegate}
            else:
                settings.pop("statusLine", None)
            _atomic_write_json(SETTINGS_PATH, settings)
            restored = True

    for p in (GLOBAL_WRAPPER, GLOBAL_LAUNCHER):
        try:
            os.remove(p)
        except OSError:
            pass

    # consent=declined로 남겨 다음 SessionStart가 재설치하지 않도록 한다.
    cfg.update({"consent": "declined", "cleaned": True, "schemaVersion": SCHEMA_VERSION})
    save_config(cfg)
    return {"ok": True, "restored": restored, "delegate": delegate}


# ─────────────────────────── SessionStart ───────────────────────────

def emit_context(text):
    """SessionStart 훅 JSON 출력으로 어시스턴트 컨텍스트에 지시를 주입한다."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }, ensure_ascii=False))


def consent_prompt_text():
    launch = os.path.join(PLUGIN_ROOT, "mcp", "launch.cjs")
    script = os.path.join(HOOK_DIR, "statusline-autosetup.py")
    base = 'node "%s" script "%s"' % (launch, script)
    return (
        "[Test-AutoEverMation] statusline auto-setup (first run). The harness statusline "
        "(plugin version + full-pipeline progress) is NOT yet configured on this machine. "
        "Ask the user ONE time, using the AskUserQuestion tool, whether to install it. It "
        "installs into the global main statusLine and preserves any existing statusline "
        "(e.g. OMC HUD) as a delegate; it shows in all sessions.\n"
        "- If the user accepts, run this Bash command:\n    %s --install --consent granted\n"
        "- If the user declines, run:\n    %s --install --consent declined\n"
        "Run exactly once and do not ask again after they answer (the choice is persisted)."
    ) % (base, base)


def do_session_start(payload):
    if os.environ.get("TAM_STATUSLINE_AUTO") == "0":
        return
    source = (payload or {}).get("source") or "startup"
    cfg = load_config()
    consent = (cfg or {}).get("consent")

    if consent == "declined":
        return
    if consent == "granted":
        # 조용한 갱신/재점유(경로 드리프트·OMC 되가져감 복구). startup/resume에서만.
        if source in ("startup", "resume"):
            try:
                do_install(consent="granted")
            except Exception:
                pass
        return
    # consent 미결정(첫 설치 직후): startup에서만 1회 확인 요청.
    if source == "startup":
        emit_context(consent_prompt_text())


# ─────────────────────────── 엔트리 ───────────────────────────

def main():
    argv = sys.argv[1:]
    try:
        if not argv:
            raw = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            do_session_start(payload)
        elif argv[0] == "--install":
            consent = "granted"
            if "--consent" in argv:
                i = argv.index("--consent")
                if i + 1 < len(argv):
                    consent = argv[i + 1]
            if consent == "declined":
                print(json.dumps(do_declined(), ensure_ascii=False))
            else:
                print(json.dumps(do_install(consent="granted"), ensure_ascii=False))
        elif argv[0] == "--uninstall":
            print(json.dumps(do_uninstall(), ensure_ascii=False))
        elif argv[0] == "--status":
            print(json.dumps({
                "config": load_config(),
                "statusLineCommand": statusline_command(),
                "pluginRoot": PLUGIN_ROOT,
                "installPath": resolve_install_path(),
                "globalWrapperExists": os.path.isfile(GLOBAL_WRAPPER),
                "globalLauncherExists": os.path.isfile(GLOBAL_LAUNCHER),
            }, ensure_ascii=False, indent=2))
        else:
            sys.stderr.write("usage: statusline-autosetup.py "
                             "[--install --consent granted|declined | --uninstall | --status]\n")
    except Exception as e:
        sys.stderr.write("statusline-autosetup: %s\n" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
