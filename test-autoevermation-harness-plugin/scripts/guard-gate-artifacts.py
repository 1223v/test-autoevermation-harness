#!/usr/bin/env python3
r"""PreToolUse Write|Edit guard, only inside the current active harness run.

Checks schema v2, approval prerequisites, stage ordering, durable resume evidence,
coverage gaps and the shared correction budget. Main execution is allowed;
spawn markers are observations, never a completion prerequisite.
Delegated test writers: {test-code-generator, coverage-closer, test-fixer, test-editor}.
An unrelated session is unaffected. Hook-owned markers and budget state cannot
be forged through Write/Edit. Official hookSpecificOutput envelope is retained.
https://code.claude.com/docs/en/hooks
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
from harness_policy import execution_policy, budget_summary

COVERAGE_ARTIFACT = "08_coverage_result.json"
PIPELINE_SCHEMA_VERSION = 2

MARKERS_DIR = ".markers"
RUN_MARKER = "run.json"
DETECT_MARKER = "pipeline-state.detected.json"

# 단계 산출물 -> 생산자 subagent_type (SKILL.md 단계 계약 표와 동기)
PRODUCERS = {
    "01_spec-reviewer_criteria.json": "spec-reviewer",
    "02_ast_targets.json": "ast-structure-analyzer",
    "03_source_seams.json": "source-code-analyzer",
    "03b_refactor_advisory.json": "refactor-advisor",
    "04_scenario_set.json": "scenario-generator",
    "05_test-gen_files.json": "test-code-generator",
    "06_run_result.json": "test-runner",
    "07_repair_result.json": "test-fixer",
    "09_conformance.json": "scenario-conformance-verifier",
}

# 오케스트레이터가 직접 기록하는 산출물 (위임 검사 대상 아님)
ORCHESTRATOR_ARTIFACTS = {
    "00_config-harness.json",
    "03c_advisory_gate.json",
    "04b_approval.json",
    "09b_conformance_repair.json",
    "pipeline_result.json",
    "_resume.json",
    "timing.json",
}

# 순서 게이트: 산출물 -> 선행 필수 산출물
# (main()의 전역 run-active 게이트를 통과한 호출에만 도달한다 — v0.32.0)
SEQUENCE_PRECONDITIONS = {
    "01_spec-reviewer_criteria.json": ("00_config-harness.json",),
    "02_ast_targets.json": ("00_config-harness.json",),
    "05_test-gen_files.json": ("04_scenario_set.json", "04b_approval.json"),
    "06_run_result.json": ("05_test-gen_files.json",),
    COVERAGE_ARTIFACT: ("06_run_result.json",),
    "09_conformance.json": (COVERAGE_ARTIFACT,),
    "09b_conformance_repair.json": ("09_conformance.json",),
}

# 영속 증거에서 안전하게 복원할 수 있는 단계만 durable-scan stub을 허용한다.
# 9단계 적합성 검증은 매 재개마다 다시 실행해야 하므로 복원 대상이 아니다.
DURABLE_STUB_ARTIFACTS = {
    "04_scenario_set.json",
    "05_test-gen_files.json",
    "06_run_result.json",
    COVERAGE_ARTIFACT,
}

# run-active 세션에서 src/test/java 기록이 허용되는 subagent_type
# (test-editor는 파이프라인 밖 사후 편집 전담 — 파이프라인이 돈 세션에서도 사용자
#  지시로 기존 테스트를 편집할 수 있어야 하므로 허용 목록에 포함한다.)
TEST_WRITE_AGENTS = {"test-code-generator", "coverage-closer", "test-fixer", "test-editor"}

_CONTRACT_HINT = "잔여 gap을 전량 보고하라. 제외는 승인된 coverage.excludes만 허용한다."
_DELEGATION_HINT = "메인이 직접 수행하거나 필요한 역할만 위임한다. 실제 결과와 선행 산출물을 확인하라."


def _deny(message: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }, ensure_ascii=False))


def _allow() -> None:
    print(json.dumps({}))


# ---------------------------------------------------------------- 공통 유틸


def _norm(path: str) -> str:
    return str(path).replace("\\", "/")


def _abspath(file_path: str, cwd: str) -> str:
    p = _norm(file_path)
    if not os.path.isabs(p):
        p = _norm(os.path.join(cwd or os.getcwd(), p))
    # 부모 디렉터리의 symlink까지 해석해 Zone A/B/C 라우팅 우회를 막는다.
    # leaf가 아직 없어도 os.path.realpath는 존재하는 부모 링크를 canonicalize한다.
    return _norm(os.path.realpath(p))


def _normalize_agent_type(raw) -> str:
    name = str(raw or "").strip()
    prefix = "test-autoevermation-harness-plugin:"
    if name.startswith(prefix):
        return name[len(prefix):]
    return "foreign:" + name if name else ""


def _read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _workspace_root(abs_path: str, cwd: str) -> str:
    """워크스페이스 루트 탐색: ① 경로 내 _workspace 세그먼트, ② 대상 프로젝트
    루트(src/test_docs 직상위)/_workspace, ③ cwd/_workspace."""
    parts = abs_path.split("/")
    comparable = [p.casefold() for p in parts] if os.name == "nt" else parts
    if "_workspace" in comparable:
        idx = comparable.index("_workspace")
        return "/".join(parts[: idx + 1])
    for seg in ("src", "test_docs"):
        if seg in comparable:
            idx = comparable.index(seg)
            candidate = "/".join(parts[:idx]) + "/_workspace"
            if os.path.isdir(candidate):
                return candidate
    return _norm(os.path.join(cwd or os.getcwd(), "_workspace"))


def _marker_session_matches(workspace: str, marker: str, session_id: str) -> bool:
    data = _read_json_file(os.path.join(workspace, MARKERS_DIR, marker))
    return isinstance(data, dict) and data.get("session_id") == session_id


def _run_active(workspace: str, session_id: str) -> bool:
    run = _read_json_file(os.path.join(workspace, MARKERS_DIR, RUN_MARKER))
    return (bool(session_id) and isinstance(run, dict) and run.get("session_id") == session_id
            and run.get("status", "active") == "active")


def _spawned(workspace: str, agent: str, session_id: str) -> bool:
    run = _read_json_file(os.path.join(workspace, MARKERS_DIR, RUN_MARKER)) or {}
    marker = _read_json_file(os.path.join(workspace, MARKERS_DIR, "spawn-%s.json" % agent)) or {}
    return (marker.get("session_id") == session_id and marker.get("run_id") == run.get("run_id"))


def _artifact_exists(workspace: str, basename: str) -> bool:
    return os.path.isfile(os.path.join(workspace, basename))


def _inside_workspace(abs_path: str, workspace: str) -> bool:
    """대상 경로가 실제 `_workspace/` 내부인지 확인한다."""
    try:
        path = os.path.normcase(os.path.realpath(abs_path))
        root = os.path.normcase(os.path.realpath(workspace))
        return os.path.commonpath((path, root)) == root
    except (OSError, ValueError):
        return False


def _parse_content(tool_input: dict):
    try:
        data = json.loads(tool_input.get("content"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _valid_threshold(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _current_coverage_thresholds(workspace: str) -> dict[str, float]:
    expected = {"line": 1.0, "branch": 1.0, "method": 1.0, "klass": 1.0}
    config = _read_json_file(os.path.join(workspace, "00_config-harness.json"))
    if not isinstance(config, dict) or config.get("schemaVersion") != PIPELINE_SCHEMA_VERSION:
        return expected
    coverage = config.get("coverage")
    if not isinstance(coverage, dict):
        return expected
    for parameter, field in (
        ("line", "line"),
        ("branch", "branch"),
        ("method", "method"),
        ("klass", "class"),
    ):
        value = coverage.get(field)
        if _valid_threshold(value):
            expected[parameter] = float(value)
    return expected


def _threshold_maps_equal(left, right) -> bool:
    names = ("line", "branch", "method", "klass")
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and all(
            _valid_threshold(left.get(name)) and _valid_threshold(right.get(name))
            for name in names
        )
        and all(abs(float(left[name]) - float(right[name])) <= 1e-12 for name in names)
    )


def _is_stub(basename: str, data, workspace: str, session_id: str) -> bool:
    """실제 detect 응답이 허용한 durable-resume stub인지 확인한다."""
    marker = _read_json_file(os.path.join(workspace, MARKERS_DIR, DETECT_MARKER))
    allowed = (
        basename in DURABLE_STUB_ARTIFACTS
        and isinstance(data, dict)
        and data.get("source") == "durable-scan"
        and isinstance(marker, dict)
        and marker.get("session_id") == session_id
        and basename in (marker.get("allowedArtifacts") or [])
    )
    if not allowed or basename != COVERAGE_ARTIFACT:
        return allowed
    current = _current_coverage_thresholds(workspace)
    config = _read_json_file(os.path.join(workspace, "00_config-harness.json")) or {}
    current_scope = {"packages": sorted(set(config.get("targets") or [])),
                     "excludes": sorted(set((config.get("coverage") or {}).get("excludes") or []))}
    if marker.get("coverageScope", {"packages": [], "excludes": []}) != current_scope:
        return False
    return (
        marker.get("coverageThresholdsMatch") is True
        and _threshold_maps_equal(marker.get("coverageThresholds"), current)
        and _threshold_maps_equal(marker.get("expectedCoverageThresholds"), current)
    )


def _check_pipeline_result(data: dict, workspace: str) -> str:
    """PipelineResult v2의 최소 완료 계약을 검사한다."""
    status = data.get("status")
    config = _read_json_file(os.path.join(workspace, "00_config-harness.json")) or {}
    if config.get("executionPolicy"):
        try:
            state = _read_json_file(os.path.join(workspace, "execution-budget.json")) or {}
            budget = budget_summary(config, state)
            summary = data.get("executionSummary") or {}
            if any(summary.get(key) != budget[key] for key in ("profile", "maxAutoFixRounds", "autoFixRounds")):
                return "executionSummary는 공용 실행 정책·실제 보정 횟수와 일치해야 한다."
            if status == "ok" and budget["pendingRound"]:
                return "보정 후 검증이 끝나지 않은 결과는 ok일 수 없다."
        except (ValueError, TypeError, KeyError):
            return "INVALID_EXECUTION_POLICY: 실행 정책/예산 상태를 확인하라."
    if status not in {"ok", "partial", "failed"}:
        return "pipeline_result.json status는 ok|partial|failed 중 하나여야 한다."
    stages = data.get("stages")
    if not isinstance(stages, dict) or not isinstance(stages.get("verifyScenarios"), dict):
        return ("pipeline_result.json은 stages.verifyScenarios 객체를 포함해야 한다 — "
                "schemaVersion만 있는 완료 표시는 허용되지 않는다.")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        return "pipeline_result.json은 비어 있지 않은 summary를 포함해야 한다."
    if status == "failed" and not _nonempty_list(data.get("errors")):
        return "failed pipeline_result.json은 errors에 실패 원인을 포함해야 한다."

    verify = stages["verifyScenarios"]
    verify_status = verify.get("status")
    if status in {"partial", "failed"} and verify_status in {"skipped", "blocked"}:
        return ""
    conformance_path = os.path.join(workspace, "09_conformance.json")
    conformance = _read_json_file(conformance_path)

    if conformance is None:
        if status == "ok":
            return "pipeline_result.json의 ok 집계 전에 09_conformance.json이 있어야 한다."
        if verify_status not in {"skipped", "blocked"}:
            return ("9단계 전 partial/failed 결과는 stages.verifyScenarios.status를 "
                    "skipped 또는 blocked로 기록해야 한다.")
        return ""

    if verify_status not in {"ok", "partial", "failed"}:
        return "09 산출물이 있으면 stages.verifyScenarios.status는 ok|partial|failed여야 한다."
    counts = {name: verify.get(name) for name in
              ("approved", "satisfied", "unsatisfied", "missing")}
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in counts.values()):
        return "stages.verifyScenarios의 네 집계값은 0 이상의 정수여야 한다."
    if counts["approved"] != (
        counts["satisfied"] + counts["unsatisfied"] + counts["missing"]
    ):
        return "stages.verifyScenarios 집계 합계가 approved와 일치하지 않는다."

    totals = conformance.get("totals") if isinstance(conformance, dict) else None
    if not isinstance(totals, dict) or any(totals.get(name) != value
                                            for name, value in counts.items()):
        return "stages.verifyScenarios 집계가 09_conformance.json totals와 일치해야 한다."
    if status == "ok":
        if verify_status != "ok" or conformance.get("status") != "ok":
            return "ok PipelineResult는 적합성 결과도 ok여야 한다."
        if counts["unsatisfied"] != 0 or counts["missing"] != 0:
            return "ok PipelineResult에는 unsatisfied/missing이 남아 있을 수 없다."
    return ""


# ------------------------------------------------------------- 08 필드 불변식 (#21)


def _nonempty_list(value) -> bool:
    return isinstance(value, list) and len(value) > 0


def _loop_ran(data: dict) -> bool:
    iterations = data.get("iterations")
    return isinstance(iterations, (int, float)) and iterations >= 1


def _check_coverage(data: dict) -> str:
    """Return a deny message for an invalid 08 artifact, or '' to allow."""
    if data.get("status") == "failed":
        return ""
    if data.get("gatePassed") is True:
        return ""
    problems = []
    iterations = data.get("iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
        problems.append("iterations는 실제 보정 횟수(0 이상의 정수)여야 한다")
    if not _nonempty_list(data.get("remainingGaps")):
        problems.append("remainingGaps 누락/빈 배열 (잔여 gap 전량 보고 위반 — 임의 제외 금지)")
    if not problems:
        return ""
    return (
        "무효 커버리지 산출물: 08_coverage_result.json이 gatePassed=false인데 "
        + ", ".join(problems)
        + ". "
        + _CONTRACT_HINT
    )


# ------------------------------------------------------------------- Zone A


def _zone_a(basename: str, tool_name: str, tool_input: dict, workspace: str,
            session_id: str, agent_type: str) -> str:
    """_workspace 단계 산출물 판정. deny 메시지 또는 ''(allow)."""
    if basename in ORCHESTRATOR_ARTIFACTS:
        if basename in {"00_config-harness.json", "_resume.json", "pipeline_result.json"}:
            if tool_name == "Edit":
                return ("스키마 산출물(%s)은 Edit로 부분 수정할 수 없다 — "
                        "전체 JSON을 Write하라." % basename)
            data = _parse_content(tool_input)
            if data is None or data.get("schemaVersion") != PIPELINE_SCHEMA_VERSION:
                return ("%s은 schemaVersion=%d인 JSON 객체여야 한다."
                        % (basename, PIPELINE_SCHEMA_VERSION))
            if basename == "00_config-harness.json" and "springProfile" not in data:
                return ("00_config-harness.json이 유효한 HarnessConfig JSON이 아니다"
                        "(springProfile 필수) — configure-harness를 호출해 Phase E "
                        "체크리스트 통과 후 생성된 config를 기록하라.")
            if basename == "00_config-harness.json":
                try:
                    execution_policy(data)
                except (ValueError, TypeError):
                    return "INVALID_EXECUTION_POLICY"
            if basename == "pipeline_result.json":
                message = _check_pipeline_result(data, workspace)
                if message:
                    return message
        if basename == "09b_conformance_repair.json" and _parse_content(tool_input) is None:
            return "09b_conformance_repair.json은 유효한 JSON 객체여야 한다."
        if basename == "09b_conformance_repair.json":
            missing = [
                pre for pre in SEQUENCE_PRECONDITIONS[basename]
                if not _artifact_exists(workspace, pre)
            ]
            if missing:
                return ("순서 게이트: %s 기록 전에 선행 산출물(%s)이 있어야 한다."
                        % (basename, ", ".join(missing)))
        return ""

    if tool_name == "Edit":
        return (
            "단계 산출물(%s)은 Edit로 부분 수정할 수 없다 — 무효 조건 검증이 "
            "불가하므로 Write로 전체를 기록하라. %s" % (basename, _CONTRACT_HINT)
        )

    data = _parse_content(tool_input)
    if data is None:
        return (
            "단계 산출물(%s)이 유효한 JSON 객체가 아니다 — 해당 단계 출력 "
            "스키마로 기록하라." % basename
        )

    stub = _is_stub(basename, data, workspace, session_id)
    if data.get("source") == "durable-scan" and not stub:
        return (
            "허용되지 않은 durable-scan stub: 실제 detect_pipeline_state 응답과 "
            "현재 세션 allowlist가 이 산출물의 복원을 증명하지 않는다."
        )

    # 08: 필드 불변식 + 루프 증거 위조 검출
    if basename == COVERAGE_ARTIFACT:
        if stub:
            if data.get("status") not in {"ok", "reused"} or data.get("gatePassed") is not True:
                return ("08 durable-scan stub은 실제 탐지에서 게이트 통과가 증명된 "
                        "status:reused|ok, gatePassed:true 산출물이어야 한다.")
        else:
            message = _check_coverage(data)
            if message:
                return message
    elif basename in PRODUCERS:
        producer = PRODUCERS[basename]
        if agent_type == producer:
            pass  # 자기 산출물
        elif agent_type:
            return (
                "%s는 %s의 산출물이다 — %s 에이전트가 기록할 수 없다. %s"
                % (basename, producer, agent_type, _DELEGATION_HINT)
            )
        elif stub:
            pass  # durable resume 복원 경로

    # 순서 게이트 (stub 면제 — 단독 스킬 세션의 정당한 경로 보호).
    # run-active는 main()의 전역 게이트가 이미 보장하므로 여기서 재검사하지 않는다.
    if not stub:
        missing = [
            pre for pre in SEQUENCE_PRECONDITIONS.get(basename, ())
            if not _artifact_exists(workspace, pre)
        ]
        if missing:
            return (
                "순서 게이트: %s 기록 전에 선행 산출물(%s)이 있어야 한다 — "
                "해당 선행 단계를 먼저 수행하라. %s"
                % (basename, ", ".join(missing), _DELEGATION_HINT)
            )
    return ""


# ------------------------------------------------------------------- Zone B


def _zone_b(workspace: str, session_id: str, agent_type: str) -> str:
    """src/test/java 기록 판정 (run-active 전제, Write/Edit 공통 — 도구 종류와 무관). deny 메시지 또는 ''."""
    if not (
        _artifact_exists(workspace, "04_scenario_set.json")
        and _artifact_exists(workspace, "04b_approval.json")
    ):
        return (
            "4.5 승인 게이트 미통과: 시나리오 설계(04_scenario_set.json)와 사용자 승인"
            "(04b_approval.json) 없이 src/test/java에 테스트를 기록할 수 없다. "
            "4단계(scenario-generator 역할 수행)→test_docs/scenarios/ 저장→AskUserQuestion "
            "승인 순서를 먼저 완료하라."
        )
    if agent_type and agent_type not in TEST_WRITE_AGENTS:
        return (
            "하네스 활성 세션에서 %s 에이전트는 src/test/java를 기록할 수 없다 "
            "(허용: %s)." % (agent_type, ", ".join(sorted(TEST_WRITE_AGENTS)))
        )
    return ""


# ------------------------------------------------------------------- Zone C


def _zone_c(abs_path: str, workspace: str) -> str:
    """test_docs 기록 판정 (run-active 전제). deny 메시지 또는 ''."""
    path = abs_path.casefold() if os.name == "nt" else abs_path
    if "/test_docs/scenarios/" in path and path.endswith(".md"):
        if not _artifact_exists(workspace, "04_scenario_set.json"):
            return (
                "test_docs/scenarios/ 문서는 4단계 시나리오 설계 산출물"
                "(04_scenario_set.json) 이후에만 기록할 수 있다 — scenario-generator를 "
                "먼저 수행하라."
            )
    if "/test_docs/refactoring/" in path:
        base = os.path.basename(path)
        if base.startswith("ra-" if os.name == "nt" else "RA-") and base.endswith(".md"):
            if not _artifact_exists(workspace, "03b_refactor_advisory.json"):
                return (
                    "test_docs/refactoring/RA-*.md는 3.5단계 산출물"
                    "(03b_refactor_advisory.json) 이후에만 기록할 수 있다 — "
                    "refactor-advisor를 먼저 수행하라."
                )
    return ""


# --------------------------------------------------------------------- main


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — fail open on malformed hook input
        _allow()
        return 0

    try:
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        file_path = str(tool_input.get("file_path", ""))
        if not file_path:
            _allow()
            return 0
        cwd = str(payload.get("cwd", "") or "")
        session_id = str(payload.get("session_id", ""))
        agent_type = _normalize_agent_type(payload.get("agent_type"))

        abs_path = _abspath(file_path, cwd)
        basename = os.path.basename(abs_path)
        if os.name == "nt":
            basename = basename.casefold()
        workspace = _workspace_root(abs_path, cwd)

        # v0.32.0 — SINGLE GATE: nothing is judged unless this session has an
        # active full-pipeline run. Before v0.30.0 the markers check and Zone A
        # ran unconditionally, so editing any `_workspace/` path was blocked even
        # in sessions that never touched the harness. That false-positive, not the
        # blocking itself, is what made the guard intolerable. Zone B/C always had
        # this gate; now every zone shares it.
        if not _run_active(workspace, session_id):
            _allow()
            return 0

        message = ""
        if _inside_workspace(abs_path, os.path.join(workspace, MARKERS_DIR)):
            message = ("_workspace/.markers는 훅 전용 실행 증거다 — "
                       "Write/Edit 도구로 생성·수정할 수 없다.")
        elif _inside_workspace(abs_path, workspace) and basename in {"execution-budget.json", "execution-budget.lock"}:
            message = "보정 예산은 harness_policy.py budget으로만 갱신한다. 자동 재개 시 초기화하지 않는다."
        elif (
            _inside_workspace(abs_path, workspace)
            and (basename in PRODUCERS
                 or basename in ORCHESTRATOR_ARTIFACTS
                 or basename == COVERAGE_ARTIFACT)
        ):
            message = _zone_a(basename, tool_name, tool_input, workspace, session_id, agent_type)
        elif "/src/test/java/" in (abs_path.lower() if os.name == "nt" else abs_path):
            message = _zone_b(workspace, session_id, agent_type)
        elif "/test_docs/" in (abs_path.lower() if os.name == "nt" else abs_path):
            message = _zone_c(abs_path, workspace)

        if message:
            _deny(message)
        else:
            _allow()
        return 0
    except Exception:  # noqa: BLE001 — a guard must never break the session
        _allow()
        return 0


if __name__ == "__main__":
    sys.exit(main())
