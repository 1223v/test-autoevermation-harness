#!/usr/bin/env python3
"""TAM statusline wrapper.

Claude Code의 statusLine 커맨드로 등록되어 두 가지 일을 한다:
1) 설치 시점에 백업해 둔 기존 statusLine 커맨드(delegate, 예: OMC HUD)를
   실행해 그 출력을 그대로 내보내고,
2) 현재 프로젝트의 `_workspace/` 산출물로부터 full-pipeline 진행률을 계산해
   `[Test-AutoEverMation#<version>] <pct>% | <stage>` 한 줄을 덧붙인다.

delegate 설정: ${CLAUDE_CONFIG_DIR:-~/.claude}/test-autoevermation-statusline.json
  {"delegate": "<원래 statusLine 커맨드 또는 null>", "pluginRoot": "<설치 경로>"}

상태줄은 UI를 깨면 안 되므로 delegate 실패와 TAM 계산 실패를 서로 격리하고
항상 exit 0으로 끝난다.
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_JSON = os.path.join(SCRIPT_DIR, "..", ".claude-plugin", "plugin.json")
CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
CONFIG_PATH = os.path.join(CONFIG_DIR, "test-autoevermation-statusline.json")

DELEGATE_TIMEOUT_SEC = 8

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
    ("08_coverage_result.json", "stage 9: mutation-test"),
    ("09_mutation_result.json", "stage 10: verify-scenarios"),
    ("10_conformance.json", "aggregating report"),
]
IDLE_STAGE_LABEL = "stage 0: configure-harness"
REPAIR_ARTIFACT = "07_repair_result.json"
REPAIR_BLOCKER = "08_coverage_result.json"  # 8단계 산출물이 생기면 7단계 표시 종료
RESULT_ARTIFACT = "pipeline_result.json"


def read_version():
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            return json.load(f).get("version", "?")
    except Exception:
        return "?"


def run_delegate(stdin_bytes):
    """설치 시점에 저장된 원래 statusLine 커맨드를 실행해 stdout을 돌려준다."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            command = json.load(f).get("delegate")
        if not command:
            return ""
        # ${CLAUDE_CONFIG_DIR:-$HOME/.claude} 같은 셸 확장을 위해 sh -c 필요
        proc = subprocess.run(
            ["/bin/sh", "-c", command],
            input=stdin_bytes,
            capture_output=True,
            timeout=DELEGATE_TIMEOUT_SEC,
        )
        return proc.stdout.decode("utf-8", "replace").rstrip("\n")
    except Exception:
        return ""


def harness_line(stdin_bytes):
    # \033[1m…\033[0m: 라벨만 굵게 (statusLine은 ANSI 코드 렌더링 지원, OMC HUD와 동일 방식)
    prefix = "\033[1m[Test-AutoEverMation#%s]\033[0m" % read_version()

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

    if os.path.exists(os.path.join(workspace, RESULT_ARTIFACT)):
        try:
            with open(os.path.join(workspace, RESULT_ARTIFACT), encoding="utf-8") as f:
                status = json.load(f).get("status", "?")
        except Exception:
            status = "?"
        return "%s 100%% | done (%s)" % (prefix, status)

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

    pct = round(100 * done / len(ORDER))
    return "%s %d%% | %s" % (prefix, pct, stage)


def main():
    stdin_bytes = sys.stdin.buffer.read()

    delegate_out = run_delegate(stdin_bytes)
    try:
        tam_line = harness_line(stdin_bytes)
    except Exception:
        tam_line = ""

    out = "\n".join(part for part in (delegate_out, tam_line) if part)
    print(out if out else "[Test-AutoEverMation] statusline unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
