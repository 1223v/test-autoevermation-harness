#!/usr/bin/env python3
"""TAM statusline wrapper.

Claude Code의 statusLine 커맨드로 등록되어 두 가지 일을 한다:
1) 설치 시점에 백업해 둔 기존 statusLine 커맨드(delegate, 예: OMC HUD)를
   실행해 그 출력을 그대로 내보내고,
2) 현재 프로젝트의 `_workspace/` 산출물로부터 full-pipeline 진행률을 계산해
   `[Test-AutoEverMation#<version>] <pct>% | <stage>` 한 줄을 덧붙인다.

이 파일은 **두 위치에서 동일하게 동작**한다:
  - 플러그인 안(`<pluginRoot>/scripts/…`) — 개발/직접 실행용.
  - 전역 사본(`${CLAUDE_CONFIG_DIR:-~/.claude}/test-autoevermation-statusline.py`)
    — 플러그인 uninstall 후에도 살아남아 **자가 원복(self-heal)** 을 수행한다.
    Claude Code 플러그인은 uninstall 훅이 없고 SessionStart 훅도 플러그인과 함께
    삭제되므로, 삭제 후에도 실행되는 유일한 아티팩트인 statusLine 커맨드(=이 사본)가
    "플러그인이 사라짐"을 감지하면 스스로 원래 statusLine으로 되돌린다.

delegate/consent 설정: ${CLAUDE_CONFIG_DIR:-~/.claude}/test-autoevermation-statusline.json
  {"delegate": "<원래 statusLine 커맨드 또는 null>",
   "pluginRoot": "<플러그인 루트>", "installPath": "<설치 경로(캐시 dir 또는 repo)>",
   "consent": "granted"|"declined"|null, "schemaVersion": 2, "cleaned": false}

상태줄은 UI를 깨면 안 되므로 delegate 실패와 TAM 계산 실패를 서로 격리하고
항상 exit 0으로 끝난다.
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
CONFIG_PATH = os.path.join(CONFIG_DIR, "test-autoevermation-statusline.json")
GLOBAL_WRAPPER = os.path.join(CONFIG_DIR, "test-autoevermation-statusline.py")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
INSTALLED_PLUGINS = os.path.join(CONFIG_DIR, "plugins", "installed_plugins.json")
PLUGIN_KEY_PREFIX = "test-autoevermation-harness-plugin@"
# statusLine 커맨드가 우리 소유인지 식별하는 지문(launcher·wrapper 공통 파일명 조각).
OWNER_MARK = "test-autoevermation-statusline"

DELEGATE_TIMEOUT_SEC = 8
PIPELINE_SCHEMA_VERSION = 2

# 단계 산출물 순서. (파일명, 그 산출물 완료 후 표시할 "현재 단계" 라벨)
# 근거: skills/full-pipeline/references/orchestration-detail.md §2.
# 진행률은 "존재하는 가장 높은 산출물" 기준 — 3.5단계 스킵·1단계 partial 진행·
# 1∥2 병렬 완료 순서 역전을 모두 견딘다. 조건부 7단계는 분모에서 제외.
ORDER = [
    ("00_config-harness.json", "stage 0.6: build-provision"),
    ("00b_build_provision.json", "stage 1-2: specs+ast"),
    ("01_spec-reviewer_criteria.json", "stage 2: analyze-ast"),
    ("02_ast_targets.json", "stage 3: analyze-source"),
    ("03_source_seams.json", "stage 3.5: refactor-advisory"),
    ("03b_refactor_advisory.json", "stage 3.5: advisory-gate"),
    ("03c_advisory_gate.json", "stage 4: generate-scenarios"),
    ("04_scenario_set.json", "stage 4.5: scenario-approval"),
    ("04b_approval.json", "stage 5: generate-tests"),
    ("05_test-gen_files.json", "stage 6: run-tests"),
    ("06_run_result.json", "stage 8: measure-coverage"),
    ("08_coverage_result.json", "stage 9: verify-scenarios"),
    ("09_conformance.json", "aggregating report"),
]
IDLE_STAGE_LABEL = "stage 0: configure-harness"
REPAIR_ARTIFACT = "07_repair_result.json"
REPAIR_BLOCKER = "08_coverage_result.json"  # 8단계 산출물이 생기면 7단계 표시 종료
# 조건부 9.5단계(적합성 자동 보정): 09b 산출물이 있고 최종 결과가 아직 없으면 표시
CONFORMANCE_REPAIR_ARTIFACT = "09b_conformance_repair.json"
RESULT_ARTIFACT = "pipeline_result.json"
# 상태 복원(durable resume) 포인터. full-pipeline Phase 0가 _workspace/ 휘발 후 영속 증거로
# 재구성할 때 남긴다({schemaVersion:2, entryStage, entryLabel, ts}). 존재 시 표시 stage를 재진입 지점으로
# clamp하고 "↩ resumed @" 를 붙여, 재개 지점보다 뒤의 stale 산출물 과대표시를 막는다.
# 규약 정본: skills/full-pipeline/references/orchestration-detail.md §2-1.
RESUME_ARTIFACT = "_resume.json"


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _registry_entries():
    """installed_plugins.json에서 이 플러그인의 엔트리 목록을 반환.
    v2 스키마({"version":2,"plugins":{...}})와 구(flat) 스키마 모두 지원한다."""
    try:
        with open(INSTALLED_PLUGINS, encoding="utf-8") as f:
            reg = json.load(f)
    except Exception:
        return []
    if not isinstance(reg, dict):
        return []
    plugins = reg.get("plugins") if isinstance(reg.get("plugins"), dict) else reg
    entries = []
    for key, val in plugins.items():
        if key.startswith(PLUGIN_KEY_PREFIX):
            entries.extend(val if isinstance(val, list) else [val])
    return [e for e in entries if isinstance(e, dict)]


def registry_install_path():
    """레지스트리가 가리키는 **현재** 설치 경로(버전업 시 즉시 새 캐시 dir).
    없으면 None."""
    for e in _registry_entries():
        if e.get("installPath"):
            return e["installPath"]
    return None


def read_version(cfg):
    """버전은 plugin.json에서 읽는다. 레지스트리의 현재 installPath를 최우선으로
    해석해 **업데이트 직후에도 세션 재시작 없이** 새 버전을 표시한다(구 캐시 dir가
    남아 있어 config의 stale pluginRoot가 여전히 유효해 보이는 문제 방지).
    실패 시 config pluginRoot → SCRIPT_DIR/.. 순으로 폴백한다."""
    candidates = []
    reg_path = registry_install_path()
    if reg_path:
        candidates.append(os.path.join(reg_path, ".claude-plugin", "plugin.json"))
    if cfg and cfg.get("pluginRoot"):
        candidates.append(os.path.join(cfg["pluginRoot"], ".claude-plugin", "plugin.json"))
    candidates.append(os.path.join(SCRIPT_DIR, "..", ".claude-plugin", "plugin.json"))
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("version", "?")
        except Exception:
            continue
    return "?"


def run_delegate(command, stdin_bytes):
    """설치 시점에 저장된 원래 statusLine 커맨드를 실행해 stdout을 돌려준다."""
    try:
        if not command:
            return ""
        # ${CLAUDE_CONFIG_DIR:-$HOME/.claude} 같은 셸 확장을 위해 셸 경유 필요.
        # delegate 문자열은 그 OS에서 저장된 것이므로 OS 기본 셸로 실행한다.
        if os.name == "nt":
            shell_cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", command]
        else:
            shell_cmd = ["/bin/sh", "-c", command]
        proc = subprocess.run(
            shell_cmd,
            input=stdin_bytes,
            capture_output=True,
            timeout=DELEGATE_TIMEOUT_SEC,
        )
        return proc.stdout.decode("utf-8", "replace").rstrip("\n")
    except Exception:
        return ""


# ─────────────────────────── self-heal (자동 uninstall) ───────────────────────────

def plugin_present(cfg):
    """플러그인이 아직 설치돼 있는가. installPath 존재 OR 레지스트리 등록 중 하나라도
    참이면 present. 둘 다 아니면 uninstall된 것으로 본다(캐시 dir 삭제 + 레지스트리 제거).
    레지스트리 조회는 v2 스키마({"plugins":{...}}) 중첩을 처리하는 _registry_entries 사용
    — 구 구현은 최상위 키만 순회해 v2에서 항상 미검출(죽은 경로)이었다."""
    install_path = cfg.get("installPath") if cfg else None
    if install_path and os.path.isdir(install_path):
        return True
    return bool(_registry_entries())


def _atomic_write_json(path, data):
    tmp = path + ".tam-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def self_heal(cfg, stdin_bytes):
    """플러그인이 사라졌을 때 한 번만: settings.json statusLine을 delegate로 원복하고
    전역 wrapper 사본을 지운 뒤 config에 cleaned=true를 남긴다. 이번 렌더는 delegate만 출력.

    launcher(cjs)는 wrapper .py가 없으면 config.delegate를 직접 실행하므로, .py를 지워도
    settings.json이 아직 launcher를 가리키는 리로드 전 구간에도 기존 상태줄은 유지된다."""
    delegate = cfg.get("delegate") if cfg else None

    # 1) settings.json 원복 (우리 소유일 때만)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        settings = None
    if isinstance(settings, dict):
        sl = settings.get("statusLine")
        cmd = sl.get("command", "") if isinstance(sl, dict) else ""
        if OWNER_MARK in cmd:
            if delegate:
                settings["statusLine"] = {"type": "command", "command": delegate}
            else:
                settings.pop("statusLine", None)
            try:
                _atomic_write_json(SETTINGS_PATH, settings)
            except Exception:
                pass

    # 2) config에 cleaned 마킹(재실행 억제) — delegate는 launcher 폴백용으로 보존
    if cfg is not None:
        cfg["cleaned"] = True
        try:
            _atomic_write_json(CONFIG_PATH, cfg)
        except Exception:
            pass

    # 3) 전역 wrapper 사본 삭제(best-effort). launcher/config는 리로드 후 자연히 미참조.
    if os.path.abspath(__file__) == os.path.abspath(GLOBAL_WRAPPER):
        try:
            os.remove(GLOBAL_WRAPPER)
        except OSError:
            pass

    return run_delegate(delegate, stdin_bytes)


# ─────────────────────────── 진행률 라인 ───────────────────────────

def _read_resume(workspace):
    """schema v2 _resume.json만 반환한다. 구 stage 9 의미는 재사용하지 않는다."""
    try:
        with open(os.path.join(workspace, RESUME_ARTIFACT), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("schemaVersion") == PIPELINE_SCHEMA_VERSION:
            return data
        return None
    except Exception:
        return None


def _valid_pipeline_result(result, workspace):
    """schema v2 완료 결과의 최소 구조와 적합성 선행 증거를 확인한다."""
    if not isinstance(result, dict) or result.get("schemaVersion") != PIPELINE_SCHEMA_VERSION:
        return False
    status = result.get("status")
    stages = result.get("stages")
    if status not in {"ok", "partial", "failed"}:
        return False
    if not isinstance(stages, dict) or not isinstance(stages.get("verifyScenarios"), dict):
        return False
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        return False
    if status == "failed" and not isinstance(result.get("errors"), list):
        return False
    if status == "failed" and not result["errors"]:
        return False

    verify = stages["verifyScenarios"]
    verify_status = verify.get("status")
    conformance_path = os.path.join(workspace, "09_conformance.json")
    try:
        with open(conformance_path, encoding="utf-8") as f:
            conformance = json.load(f)
    except Exception:
        conformance = None

    if not isinstance(conformance, dict):
        return status in {"partial", "failed"} and verify_status in {"skipped", "blocked"}
    if verify_status not in {"ok", "partial", "failed"}:
        return False
    names = ("approved", "satisfied", "unsatisfied", "missing")
    counts = {name: verify.get(name) for name in names}
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in counts.values()):
        return False
    if counts["approved"] != (
        counts["satisfied"] + counts["unsatisfied"] + counts["missing"]
    ):
        return False
    totals = conformance.get("totals")
    if not isinstance(totals, dict) or any(totals.get(name) != value
                                            for name, value in counts.items()):
        return False
    if status == "ok":
        return (
            verify_status == "ok"
            and conformance.get("status") == "ok"
            and counts["unsatisfied"] == 0
            and counts["missing"] == 0
        )
    return True


def _resume_order_index(resume):
    """_resume.json → ORDER 인덱스(표시 stage/pct clamp용).
    entryLabel 정확 일치 우선, 실패 시 'stage <entryStage>:' 접두 일치로 폴백. 못 찾으면 None."""
    label = resume.get("entryLabel")
    for i, (_artifact, next_label) in enumerate(ORDER):
        if next_label == label:
            return i
    stage_num = resume.get("entryStage")
    if stage_num is not None:
        prefix = "stage %s:" % stage_num
        for i, (_artifact, next_label) in enumerate(ORDER):
            if next_label.startswith(prefix):
                return i
    return None


def harness_line(cfg, stdin_bytes):
    # \033[1m…\033[0m: 라벨만 굵게 (statusLine은 ANSI 코드 렌더링 지원, OMC HUD와 동일 방식)
    prefix = "\033[1m[Test-AutoEverMation#%s]\033[0m" % read_version(cfg)

    try:
        data = json.loads(stdin_bytes) if stdin_bytes else {}
    except Exception:
        data = {}
    cwd = (
        (data.get("workspace") or {}).get("current_dir")
        or data.get("cwd")
        or os.getcwd()
    )

    workspace = os.path.join(cwd, "_workspace")
    if not os.path.isdir(workspace):
        return prefix  # 파이프라인 없음 — 버전만 표시

    result_path = os.path.join(workspace, RESULT_ARTIFACT)
    if os.path.exists(result_path):
        try:
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
        except Exception:
            result = None
        if _valid_pipeline_result(result, workspace):
            return "%s 100%% | done (%s)" % (prefix, result.get("status", "?"))

    done = 0
    stage = IDLE_STAGE_LABEL
    for i, (artifact, next_label) in enumerate(ORDER):
        if os.path.exists(os.path.join(workspace, artifact)):
            done = i + 1
            stage = next_label
    # 조건부 7단계: 08 산출물이 아직 없고 07 수리 결과가 있으면 그 단계를 표시
    if os.path.exists(os.path.join(workspace, REPAIR_ARTIFACT)) and not os.path.exists(
        os.path.join(workspace, REPAIR_BLOCKER)
    ):
        stage = "stage 7: repair-tests"
    # 조건부 9.5단계: 적합성 자동 보정 루프 진행 중
    if os.path.exists(os.path.join(workspace, CONFORMANCE_REPAIR_ARTIFACT)):
        stage = "stage 9.5: conformance-repair"

    # 상태 복원(durable resume): _resume.json이 있으면 표시 stage를 재진입 지점으로 clamp하고
    # "↩ resumed @" 를 붙인다 — 재개 지점보다 뒤의 stale 산출물이 있어도 과대표시하지 않는다.
    resume = _read_resume(workspace)
    if resume:
        idx = _resume_order_index(resume)
        if idx is not None:
            done = idx + 1
            stage = ORDER[idx][1]
        else:
            stage = resume.get("entryLabel") or stage
        pct = round(100 * done / len(ORDER))
        return "%s %d%% | ↩ resumed @ %s" % (prefix, pct, stage)

    pct = round(100 * done / len(ORDER))
    return "%s %d%% | %s" % (prefix, pct, stage)


def main():
    stdin_bytes = sys.stdin.buffer.read()
    cfg = load_config()

    # 자가 원복: 플러그인이 사라졌고 아직 정리 전이면 원래 상태줄로 복구하고 종료.
    if cfg and not cfg.get("cleaned") and not plugin_present(cfg):
        out = self_heal(cfg, stdin_bytes)
        print(out if out else "")
        return 0

    delegate_cmd = cfg.get("delegate") if cfg else None
    delegate_out = run_delegate(delegate_cmd, stdin_bytes)
    try:
        tam_line = harness_line(cfg, stdin_bytes)
    except Exception:
        tam_line = ""

    out = "\n".join(part for part in (delegate_out, tam_line) if part)
    print(out if out else "[Test-AutoEverMation] statusline unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
