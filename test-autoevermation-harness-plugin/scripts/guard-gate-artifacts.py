#!/usr/bin/env python3
r"""guard-gate-artifacts.py

PreToolUse hook for the Spring Test Harness plugin (matcher: ``Write|Edit``).

v0.22.0: 8/9단계 게이트 필드 불변식(#21)에 더해, **위임(delegation)·산출물 순서를
물리 강제**한다. record-run-context.py가 남기는 ``_workspace/.markers/`` 증거
(run.json / spawn-<agent>.json / pipeline-state.detected.json)를 판정에 사용한다.
배경: v0.21.0 SSOT 통합 이후 오케스트레이터가 서브에이전트 위임과 산출물 영속화를
인라인 수행으로 우회한 실세션 회귀 — prose는 강제가 아니므로 훅으로 차단한다.

Decision table:

Zone A — ``_workspace`` 단계 산출물 (basename 매칭):
  * 오케스트레이터 소유 산출물(00/03c/04b/10b/_resume/timing)
      - 00_config-harness.json: Write가 JSON 객체 + "springProfile" 포함 필수
        (빈 껍데기 config 차단), Edit는 deny. 그 외 -> allow
      - 나머지 -> allow
  * producer 산출물(01/02/03/03b/04/05/06/07/10) 및 08/09:
      - Edit                                    -> deny (전체 Write만 — 검증 불가)
      - Write, 내용이 JSON 객체 아님             -> deny
  * 08/09 필드 불변식(#21)                       -> 기존 로직 유지 (아래 참조)
  * 08: gatePassed=false && iterations>=1 && spawn-coverage-closer 부재
                                                -> deny (루프 증거 위조 — 미위임)
  * 09: status=skipped + reason=PITEST_DISABLED + null 측정값
                                                -> allow (명시적 선택 기능 비활성)
  * 09: 그 외 thresholdMet=false && iterations>=1 && spawn-mutation-analyst 부재
                                                -> deny (동일)
  * producer 산출물 provenance:
      - agent_type == producer                  -> allow (자기 산출물)
      - 메인 에이전트 + stub(content.source=="durable-scan" &&
        pipeline-state.detected.json 세션 일치)  -> allow (durable resume 복원)
      - 메인 에이전트 + spawn-<producer> 마커(세션 일치)
                                                -> allow (위임 후 결과 기록)
      - 그 외                                    -> deny (위임 없이 산출물 기록)
  * 순서 게이트(run-active일 때만, stub 면제):
      01|02 without 00 / 05 without 04∧04b / 06 without 05
      / 08 without 06 / 09 without 08           -> deny

Zone B — ``src/test/java/**`` (run-active일 때만; 비활성 = 일반 개발 세션 -> allow):
  * 04_scenario_set.json 또는 04b_approval.json 부재
                                                -> deny (4.5 승인 전 기록 금지 — 누구든)
  * agent_type ∈ {test-code-generator, coverage-closer,
    mutation-analyst, test-fixer}               -> allow
  * 메인 에이전트 + Edit + spawn-test-fixer 마커(세션 일치)
                                                -> allow (7/10.5단계 patch-apply)
  * 그 외                                        -> deny (오케스트레이터 인라인 작성 금지)

Zone C — ``test_docs/**`` (run-active일 때만):
  * test_docs/scenarios/*.md without 04         -> deny
  * test_docs/refactoring/RA-*.md without 03b   -> deny
  * 그 외                                        -> allow

Zone D — 그 외 전부 allow.
인프라 오류(malformed stdin/내부 예외)          -> allow (fail-open — 훅이 세션을
                                                   깨서는 안 된다; 판정 로직 자체는
                                                   fail-closed).

Hook JSON 입력 (실증됨, probe-hook-stdin.py 2026-07):
  { "tool_name": "Write"|"Edit", "tool_input": {"file_path", "content"(Write)},
    "session_id": "...", "cwd": "...",
    "agent_id"/"agent_type": 서브에이전트 내부 호출 시 채워짐(메인은 null) }

Hook JSON 출력 (PreToolUse 결정 계약 — hookSpecificOutput 중첩 필수; top-level
permissionDecision은 무시되어 fail-open):
  Allow:  {}
  Deny:   {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny",
                                  "permissionDecisionReason": "<reason>"}}

Stdlib only (json, sys, os). Windows 경로(``\``) 정규화.
"""

import json
import os
import sys

COVERAGE_ARTIFACT = "08_coverage_result.json"
MUTATION_ARTIFACT = "09_mutation_result.json"

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
    "10_conformance.json": "scenario-conformance-verifier",
}

# 오케스트레이터가 직접 기록하는 산출물 (위임 검사 대상 아님)
ORCHESTRATOR_ARTIFACTS = {
    "00_config-harness.json",
    "03c_advisory_gate.json",
    "04b_approval.json",
    "10b_conformance_repair.json",
    "_resume.json",
    "timing.json",
}

# 순서 게이트: 산출물 -> 선행 필수 산출물 (run-active일 때만 적용)
SEQUENCE_PRECONDITIONS = {
    "01_spec-reviewer_criteria.json": ("00_config-harness.json",),
    "02_ast_targets.json": ("00_config-harness.json",),
    "05_test-gen_files.json": ("04_scenario_set.json", "04b_approval.json"),
    "06_run_result.json": ("05_test-gen_files.json",),
    COVERAGE_ARTIFACT: ("06_run_result.json",),
    MUTATION_ARTIFACT: (COVERAGE_ARTIFACT,),
}

# run-active 세션에서 src/test/java 기록이 허용되는 subagent_type
TEST_WRITE_AGENTS = {"test-code-generator", "coverage-closer", "mutation-analyst", "test-fixer"}

_CONTRACT_HINT = (
    "(fallback-policy.md #21) 게이트 미달 시 coverage-closer/mutation-analyst "
    "루프를 실제 수행한 뒤 잔여를 전량 보고하고 기록하라. RA advisory는 "
    "8단계와 활성화된 9단계 게이트의 면제·스킵 사유가 아니며, '구조적 커버리지 한계' 판단은 "
    "에이전트의 remainingGaps[].reason/survivingMutants[]로만 성립한다. "
    "스코프 제외는 HarnessConfig.coverage.excludes(사용자 승인)로만 가능하다."
)

_DELEGATION_HINT = (
    "full-pipeline 단계 계약: 각 단계는 지정된 subagent에 Task 위임으로만 수행하며, "
    "위임 없이 오케스트레이터가 직접 수행한 단계는 무효다. 해당 단계를 "
    "Task(subagent_type=...)로 재실행한 뒤 산출물을 기록하라."
)


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
    return p


def _normalize_agent_type(raw) -> str:
    """플러그인 스코프 접두("plugin:agent")를 제거해 bare 이름으로 정규화."""
    name = _norm(raw or "")
    for sep in (":", "/"):
        if sep in name:
            name = name.rsplit(sep, 1)[1]
    return name.strip()


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
    if "_workspace" in parts:
        idx = parts.index("_workspace")
        return "/".join(parts[: idx + 1])
    for seg in ("src", "test_docs"):
        if seg in parts:
            idx = parts.index(seg)
            candidate = "/".join(parts[:idx]) + "/_workspace"
            if os.path.isdir(candidate):
                return candidate
    return _norm(os.path.join(cwd or os.getcwd(), "_workspace"))


def _marker_session_matches(workspace: str, marker: str, session_id: str) -> bool:
    data = _read_json_file(os.path.join(workspace, MARKERS_DIR, marker))
    return isinstance(data, dict) and data.get("session_id") == session_id


def _run_active(workspace: str, session_id: str) -> bool:
    return _marker_session_matches(workspace, RUN_MARKER, session_id)


def _spawned(workspace: str, agent: str, session_id: str) -> bool:
    return _marker_session_matches(workspace, "spawn-%s.json" % agent, session_id)


def _artifact_exists(workspace: str, basename: str) -> bool:
    return os.path.isfile(os.path.join(workspace, basename))


def _configured_mutation_enabled(workspace: str):
    """Read opt-in: no config is unknown; a legacy config without the field is disabled."""
    config = _read_json_file(os.path.join(workspace, "00_config-harness.json"))
    if not isinstance(config, dict):
        return None
    if "mutation" not in config:
        return False
    mutation = config.get("mutation")
    if not isinstance(mutation, dict):
        return None
    if "enabled" not in mutation:
        return False
    enabled = mutation.get("enabled")
    return enabled if isinstance(enabled, bool) else None


def _parse_content(tool_input: dict):
    try:
        data = json.loads(tool_input.get("content"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _is_stub(data, workspace: str, session_id: str) -> bool:
    """durable-resume 복원 stub: source=="durable-scan" + detect 호출 증거(세션 일치)."""
    return (
        isinstance(data, dict)
        and data.get("source") == "durable-scan"
        and _marker_session_matches(workspace, DETECT_MARKER, session_id)
    )


# ---------------------------------------------------------- 08/09 필드 불변식 (#21)


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
    if not _loop_ran(data):
        problems.append("iterations<1 (coverage-closer 루프 미수행)")
    if not _nonempty_list(data.get("remainingGaps")):
        problems.append("remainingGaps 누락/빈 배열 (잔여 gap 전량 보고 위반 — 임의 제외 금지)")
    if not problems:
        return ""
    return (
        "게이트 미수행 산출물: 08_coverage_result.json이 gatePassed=false인데 "
        + ", ".join(problems)
        + ". "
        + _CONTRACT_HINT
    )


def _check_mutation(data: dict, mutation_enabled=None, enforce_config: bool = False) -> str:
    """Return a deny message for an invalid 09 artifact, or '' to allow."""
    if data.get("status") == "skipped":
        valid_disabled = (
            data.get("reason") == "PITEST_DISABLED"
            and data.get("mutationScore") is None
            and data.get("thresholdMet") is None
            and data.get("iterations") == 0
        )
        if valid_disabled:
            if mutation_enabled is True or (enforce_config and mutation_enabled is None):
                return (
                    "게이트 미수행 산출물: 활성 파이프라인에서 "
                    "HarnessConfig.mutation.enabled=false가 확인되지 않아 "
                    "PITEST_DISABLED skip을 기록할 수 없다. 설정을 확인하거나 9단계를 수행하라."
                )
            return ""
        return (
            "게이트 미수행 산출물: 09_mutation_result.json의 skipped 상태는 "
            "HarnessConfig.mutation.enabled=false일 때 reason=PITEST_DISABLED, "
            "mutationScore=null, thresholdMet=null, iterations=0 계약으로만 허용된다."
        )
    if data.get("status") == "failed":
        return ""
    if data.get("thresholdMet") is True:
        return ""
    problems = []
    if not _loop_ran(data):
        problems.append("iterations<1 (mutation-analyst 루프 미수행)")
    if not _nonempty_list(data.get("survivingMutants")):
        problems.append("survivingMutants 누락/빈 배열 (잔여 survivor 전량 보고 위반 — 임의 무시 금지)")
    if not problems:
        return ""
    return (
        "게이트 미수행 산출물: 09_mutation_result.json이 thresholdMet=false인데 "
        + ", ".join(problems)
        + ". "
        + _CONTRACT_HINT
    )


# ------------------------------------------------------------------- Zone A


def _zone_a(basename: str, tool_name: str, tool_input: dict, workspace: str,
            session_id: str, agent_type: str) -> str:
    """_workspace 단계 산출물 판정. deny 메시지 또는 ''(allow)."""
    if basename in ORCHESTRATOR_ARTIFACTS:
        if basename == "00_config-harness.json":
            if tool_name == "Edit":
                return ("00_config-harness.json은 Edit로 부분 수정할 수 없다 — "
                        "configure-harness로 HarnessConfig 전체를 Write하라.")
            data = _parse_content(tool_input)
            if data is None or "springProfile" not in data:
                return ("00_config-harness.json이 유효한 HarnessConfig JSON이 아니다"
                        "(springProfile 필수) — configure-harness를 호출해 Phase E "
                        "체크리스트 통과 후 생성된 config를 기록하라.")
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

    stub = _is_stub(data, workspace, session_id)

    # 08/09: 필드 불변식 + 루프 증거 위조 검출
    if basename in (COVERAGE_ARTIFACT, MUTATION_ARTIFACT):
        message = (
            _check_coverage(data)
            if basename == COVERAGE_ARTIFACT
            else _check_mutation(
                data,
                _configured_mutation_enabled(workspace)
                if _run_active(workspace, session_id) else None,
                enforce_config=_run_active(workspace, session_id),
            )
        )
        if message:
            return message
        if basename == COVERAGE_ARTIFACT:
            gate_failed, loop_agent = data.get("gatePassed") is not True, "coverage-closer"
        else:
            gate_failed, loop_agent = data.get("thresholdMet") is not True, "mutation-analyst"
        if (
            data.get("status") != "failed"
            and gate_failed
            and _loop_ran(data)
            and not agent_type
            and not _spawned(workspace, loop_agent, session_id)
        ):
            return (
                "루프 증거 위조 의심: %s이 iterations>=1을 주장하지만 이 세션에서 "
                "%s가 스폰된 기록이 없다. 게이트 루프는 %s 에이전트 위임으로만 "
                "수행할 수 있다. %s" % (basename, loop_agent, loop_agent, _DELEGATION_HINT)
            )
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
        elif not _spawned(workspace, producer, session_id):
            return (
                "위임 없이 산출물 기록: %s를 쓰려면 이 세션에서 "
                "Task(subagent_type=%s)로 해당 단계를 실제 수행했어야 한다. %s"
                % (basename, producer, _DELEGATION_HINT)
            )

    # 순서 게이트 (run-active 한정, stub 면제 — 단독 스킬 세션의 정당한 경로 보호)
    if not stub and _run_active(workspace, session_id):
        missing = [
            pre for pre in SEQUENCE_PRECONDITIONS.get(basename, ())
            if not _artifact_exists(workspace, pre)
        ]
        if missing:
            return (
                "순서 게이트: %s 기록 전에 선행 산출물(%s)이 있어야 한다 — "
                "해당 선행 단계를 먼저 위임 수행하라. %s"
                % (basename, ", ".join(missing), _DELEGATION_HINT)
            )
    return ""


# ------------------------------------------------------------------- Zone B


def _zone_b(tool_name: str, workspace: str, session_id: str, agent_type: str) -> str:
    """src/test/java 기록 판정 (run-active 전제). deny 메시지 또는 ''."""
    if not (
        _artifact_exists(workspace, "04_scenario_set.json")
        and _artifact_exists(workspace, "04b_approval.json")
    ):
        return (
            "4.5 승인 게이트 미통과: 시나리오 설계(04_scenario_set.json)와 사용자 승인"
            "(04b_approval.json) 없이 src/test/java에 테스트를 기록할 수 없다. "
            "4단계(scenario-generator 위임)→test_docs/scenarios/ 저장→AskUserQuestion "
            "승인 순서를 먼저 완료하라."
        )
    if agent_type in TEST_WRITE_AGENTS:
        return ""
    if not agent_type and tool_name == "Edit" and _spawned(workspace, "test-fixer", session_id):
        return ""  # 7/10.5단계: test-fixer patch를 오케스트레이터가 적용
    if agent_type:
        return (
            "하네스 활성 세션에서 %s 에이전트는 src/test/java를 기록할 수 없다 "
            "(허용: %s)." % (agent_type, ", ".join(sorted(TEST_WRITE_AGENTS)))
        )
    return (
        "하네스 활성 세션에서 오케스트레이터의 테스트 인라인 작성/수정 금지: "
        "5단계 생성은 Task(subagent_type=test-code-generator)에, 실패 보정은 "
        "Task(subagent_type=test-fixer)에 위임하라. %s" % _DELEGATION_HINT
    )


# ------------------------------------------------------------------- Zone C


def _zone_c(abs_path: str, workspace: str) -> str:
    """test_docs 기록 판정 (run-active 전제). deny 메시지 또는 ''."""
    path = abs_path
    if "/test_docs/scenarios/" in path and path.endswith(".md"):
        if not _artifact_exists(workspace, "04_scenario_set.json"):
            return (
                "test_docs/scenarios/ 문서는 4단계 시나리오 설계 산출물"
                "(04_scenario_set.json) 이후에만 기록할 수 있다 — scenario-generator를 "
                "먼저 위임 수행하라."
            )
    if "/test_docs/refactoring/" in path:
        base = os.path.basename(path)
        if base.startswith("RA-") and base.endswith(".md"):
            if not _artifact_exists(workspace, "03b_refactor_advisory.json"):
                return (
                    "test_docs/refactoring/RA-*.md는 3.5단계 산출물"
                    "(03b_refactor_advisory.json) 이후에만 기록할 수 있다 — "
                    "refactor-advisor를 먼저 위임 수행하라."
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
        workspace = _workspace_root(abs_path, cwd)

        message = ""
        if basename in PRODUCERS or basename in ORCHESTRATOR_ARTIFACTS or basename in (
            COVERAGE_ARTIFACT, MUTATION_ARTIFACT
        ):
            message = _zone_a(basename, tool_name, tool_input, workspace, session_id, agent_type)
        elif "/src/test/java/" in abs_path:
            if _run_active(workspace, session_id):
                message = _zone_b(tool_name, workspace, session_id, agent_type)
        elif "/test_docs/" in abs_path:
            if _run_active(workspace, session_id):
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
