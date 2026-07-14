#!/usr/bin/env python3
r"""record-run-context.py

PreToolUse hook (matcher: ``Skill|Task|Agent``) + PostToolUse hook
(matcher: ``*detect_pipeline_state``) for the Spring Test Harness plugin.

full-pipeline 실행의 **물리 강제(위임 계약)**를 위한 실행 컨텍스트 기록자.
guard-gate-artifacts.py가 판정에 사용하는 마커를 ``_workspace/.markers/``에 남긴다:

  * ``run.json``                        — full-pipeline Skill 호출 시 cwd와 대상
                                          projectRoot에 기록. {"session_id", "ts",
                                          "projectRoot", "projectRootExplicit"}. 이 세션이
                                          "하네스 활성(run-active)"임을 나타내는 신호.
  * ``spawn-<subagent_type>.json``      — Task/Agent 스폰 시 기록. {"session_id", "ts"}.
                                          "해당 단계가 실제로 위임되었다"는 물리 증거.
  * ``pipeline-state.detected.json``    — detect_pipeline_state의 실제 요청 root·커버리지
                                          임계값과 응답을 결합해 복원 가능한 산출물 allowlist를
                                          대상 projectRoot에 기록. durable-resume stub의 전제.

Decision table:
  PreToolUse Skill:
    * full-pipeline 아님                        -> allow (무동작)
    * full-pipeline                             -> 부수효과: 이전 실행 마커 청소 +
                                                   run.json 기록; allow +
                                                   additionalContext(단계 계약 요약)
  PreToolUse Task|Agent:
    * subagent_type == test-code-generator      -> run 활성인데 04_scenario_set.json
                                                   또는 04b_approval.json 부재면 deny
                                                   (4.5 승인 게이트 선행 — 스폰 시점 차단);
                                                   아니면 spawn 마커 기록 후 allow
    * 그 외 subagent_type                        -> spawn 마커 기록 후 allow
  PostToolUse detect_pipeline_state             -> 실제 응답 기반 allowedArtifacts 기록; allow
  내부 오류/파싱 실패/마커 기록 실패             -> allow (인프라 fail-open — 훅이 세션을
                                                   깨서는 안 된다; 판정은 guard가 담당)

Hook 출력 스키마 (Claude Code PreToolUse 계약 — 결정은 hookSpecificOutput 중첩 필수):
  Allow(무의견):      {}
  Allow+컨텍스트:     {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "additionalContext": "<text>"}}
  Deny:               {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": "<reason>"}}

Stdlib only (json, os, sys, time). Windows 경로(``\``) 정규화.
"""

import json
import os
import sys
import time

MARKERS_DIR = ".markers"
RUN_MARKER = "run.json"
DETECT_MARKER = "pipeline-state.detected.json"

SCENARIO_SET = "04_scenario_set.json"
APPROVAL = "04b_approval.json"

# 스폰 마커를 남길 파이프라인 단계 subagent (스코프 접두는 정규화 후 비교)
PIPELINE_AGENTS = {
    "spec-reviewer",
    "ast-structure-analyzer",
    "source-code-analyzer",
    "refactor-advisor",
    "scenario-generator",
    "test-code-generator",
    "test-runner",
    "test-fixer",
    "coverage-closer",
    "scenario-conformance-verifier",
}

_STAGE_CONTRACT_REMINDER = (
    "[full-pipeline 단계 계약 — 훅 물리 강제] 각 단계는 SKILL.md 단계 계약 표의 "
    "subagent에 Task 위임으로만 수행한다. 위임 없이 오케스트레이터가 직접 수행한 "
    "단계는 무효다: guard-gate-artifacts 훅이 (1) spawn 마커 없는 _workspace 단계 "
    "산출물 기록, (2) 하네스 활성 세션에서 오케스트레이터의 src/test/java 기록, "
    "(3) 선행 산출물 없는 후속 산출물 기록(순서 게이트)을 deny한다. 산출물 JSON은 "
    "단계 완료 즉시 Write하라 — 산출물 없는 단계는 미수행으로 간주되어 후속 기록이 "
    "차단된다. durable-resume stub은 detect_pipeline_state 호출 이후에만 유효하다."
)


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _allow() -> None:
    _print({})


def _allow_with_context(text: str) -> None:
    _print({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    })


def _deny(message: str) -> None:
    _print({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    })


def _canonical_root(value, cwd: str) -> str:
    raw = str(value or ".").replace("\\", "/")
    if not os.path.isabs(raw):
        raw = os.path.join(cwd, raw)
    return os.path.realpath(os.path.expanduser(raw))


def _cwd_root(payload: dict) -> str:
    return _canonical_root(payload.get("cwd") or os.getcwd(), os.getcwd())


def _workspace_for_root(root: str) -> str:
    return os.path.join(root, "_workspace")


def _markers_for_root(root: str) -> str:
    return os.path.join(_workspace_for_root(root), MARKERS_DIR)


def _workspace_root(payload: dict, session_id: str | None = None) -> str:
    cwd_root = _cwd_root(payload)
    if session_id:
        run = _read_json(os.path.join(_markers_for_root(cwd_root), RUN_MARKER))
        if isinstance(run, dict) and run.get("session_id") == session_id:
            project_root = run.get("projectRoot")
            if isinstance(project_root, str) and project_root:
                return _workspace_for_root(_canonical_root(project_root, cwd_root))
    return _workspace_for_root(cwd_root)


def _markers_dir(payload: dict, session_id: str | None = None) -> str:
    return os.path.join(_workspace_root(payload, session_id), MARKERS_DIR)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _write_marker(path: str, session_id: str, extra: dict | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    marker = {"session_id": session_id, "ts": time.time()}
    if isinstance(extra, dict):
        marker.update(extra)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)


def _normalize_agent_type(raw: str) -> str:
    # "plugin-name:agent" / "plugin_name__agent" 등 스코프 접두 제거 → 마지막 세그먼트
    name = str(raw).replace("\\", "/")
    for sep in (":", "/"):
        if sep in name:
            name = name.rsplit(sep, 1)[1]
    return name.strip()


def _run_active(markers: str, session_id: str) -> bool:
    run = _read_json(os.path.join(markers, RUN_MARKER))
    return isinstance(run, dict) and run.get("session_id") == session_id


def _extract_project_root(value):
    """Skill 입력의 JSON 객체/문자열에서 projectRoot를 찾는다."""
    if isinstance(value, dict):
        project_root = value.get("projectRoot") or value.get("project_root")
        if isinstance(project_root, str) and project_root.strip():
            normalized = project_root.strip()
            if normalized.lower() not in {"미지정", "undefined", "null"}:
                return normalized
        for key in ("args", "arguments", "input"):
            project_root = _extract_project_root(value.get(key))
            if project_root:
                return project_root
        return None
    if isinstance(value, str):
        decoder = json.JSONDecoder()
        for index, char in enumerate(value):
            if char != "{":
                continue
            try:
                parsed, _end = decoder.raw_decode(value[index:])
            except Exception:  # noqa: BLE001
                continue
            project_root = _extract_project_root(parsed)
            if project_root:
                return project_root
        return None
    return None


def _clear_invocation_markers(markers: str, *, remove_run: bool = False) -> None:
    try:
        if not os.path.isdir(markers):
            return
        for entry in os.listdir(markers):
            if entry.startswith("spawn-") or entry == DETECT_MARKER or (
                remove_run and entry == RUN_MARKER
            ):
                try:
                    os.remove(os.path.join(markers, entry))
                except OSError:
                    pass
    except OSError:
        pass


def _handle_skill(payload: dict, tool_input: dict, session_id: str) -> None:
    skill_name = str(
        tool_input.get("skill") or tool_input.get("name") or tool_input.get("command") or ""
    )
    if "full-pipeline" not in skill_name:
        _allow()
        return

    cwd_root = _cwd_root(payload)
    cwd_markers = _markers_for_root(cwd_root)
    previous = _read_json(os.path.join(cwd_markers, RUN_MARKER))
    previous_root = None
    if isinstance(previous, dict) and isinstance(previous.get("projectRoot"), str):
        previous_root = _canonical_root(previous["projectRoot"], cwd_root)

    requested = _extract_project_root(tool_input)
    target_root = _canonical_root(requested, cwd_root) if requested else cwd_root
    active_roots = {cwd_root, target_root}
    cleanup_roots = set(active_roots)
    if previous_root:
        cleanup_roots.add(previous_root)

    # 같은 Claude 세션에서 full-pipeline을 다시 호출해도 이전 실행의 spawn/detect
    # 증거를 재사용할 수 없다. 매 invocation마다 단계 위임 증거를 새로 수집한다.
    for root in cleanup_roots:
        _clear_invocation_markers(
            _markers_for_root(root),
            remove_run=root not in active_roots,
        )
    route = {
        "projectRoot": target_root,
        "projectRootExplicit": requested is not None,
    }
    for root in active_roots:
        _write_marker(
            os.path.join(_markers_for_root(root), RUN_MARKER),
            session_id,
            route,
        )
    _allow_with_context(_STAGE_CONTRACT_REMINDER)


def _handle_spawn(payload: dict, tool_input: dict, session_id: str) -> None:
    agent_type = _normalize_agent_type(tool_input.get("subagent_type") or "")
    if agent_type not in PIPELINE_AGENTS:
        _allow()
        return

    markers = _markers_dir(payload, session_id)
    workspace = _workspace_root(payload, session_id)

    if agent_type == "test-code-generator" and _run_active(markers, session_id):
        has_scenarios = os.path.isfile(os.path.join(workspace, SCENARIO_SET))
        has_approval = os.path.isfile(os.path.join(workspace, APPROVAL))
        if not (has_scenarios and has_approval):
            missing = []
            if not has_scenarios:
                missing.append(SCENARIO_SET)
            if not has_approval:
                missing.append(APPROVAL)
            _deny(
                "4.5 승인 게이트 미통과: %s 부재 상태에서 test-code-generator를 스폰할 수 "
                "없다. 4단계(scenario-generator 위임)로 시나리오를 설계하고 "
                "test_docs/scenarios/*.md 저장 후 AskUserQuestion 승인을 받아 "
                "04b_approval.json을 기록한 뒤 재시도하라." % ", ".join(missing)
            )
            return

    _write_marker(os.path.join(markers, "spawn-%s.json" % agent_type), session_id)
    _allow()


def _extract_detect_result(value):
    """PostToolUse의 도구별 응답 모양에서 detect 결과 객체를 추출한다."""
    if isinstance(value, dict):
        if (
            value.get("status") == "ok"
            and "recommendedEntryStage" in value
            and "harnessProvenance" in value
        ):
            return value
        for key in ("structuredContent", "structured_content", "result", "content", "text"):
            result = _extract_detect_result(value.get(key))
            if result is not None:
                return result
        return None
    if isinstance(value, list):
        for item in value:
            result = _extract_detect_result(item)
            if result is not None:
                return result
        return None
    if isinstance(value, str):
        try:
            return _extract_detect_result(json.loads(value))
        except Exception:  # noqa: BLE001
            return None
    return None


def _allowed_stub_artifacts(
    result: dict, *, allow_coverage_stub: bool = True
) -> list[str]:
    """탐지 결과가 실제로 증명한 durable 복원 산출물만 반환한다."""
    if result.get("status") != "ok" or result.get("harnessProvenance") is not True:
        return []
    allowed: list[str] = []
    scenarios = result.get("scenarios") or {}
    if isinstance(scenarios, dict) and (scenarios.get("approved") or 0) > 0:
        allowed.append("04_scenario_set.json")
    if result.get("hasTests") is True:
        allowed.append("05_test-gen_files.json")

    entry = result.get("recommendedEntryStage")
    junit = result.get("junitReport") or {}
    junit_green = (
        isinstance(junit, dict)
        and junit.get("present") is True
        and isinstance(junit.get("passed"), int)
        and not isinstance(junit.get("passed"), bool)
        and junit.get("passed") > 0
        and junit.get("failed") == 0
    )
    if isinstance(entry, (int, float)) and entry >= 8 and junit_green:
        allowed.append("06_run_result.json")

    jacoco = result.get("jacocoReport") or {}
    if (
        isinstance(entry, (int, float))
        and entry >= 9
        and junit_green
        and isinstance(jacoco, dict)
        and jacoco.get("present") is True
        and jacoco.get("gatePassed") is True
        and allow_coverage_stub
    ):
        allowed.append("08_coverage_result.json")
    return allowed


def _valid_threshold(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _expected_coverage_thresholds(root: str) -> dict[str, float]:
    expected = {"line": 1.0, "branch": 1.0, "method": 1.0, "klass": 1.0}
    config = _read_json(os.path.join(root, "_workspace", "00_config-harness.json"))
    if not isinstance(config, dict) or config.get("schemaVersion") != 2:
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


def _requested_coverage_thresholds(tool_input: dict) -> dict[str, float] | None:
    thresholds: dict[str, float] = {}
    for parameter in ("line", "branch", "method", "klass"):
        value = tool_input.get(parameter, 1.0)
        if not _valid_threshold(value):
            return None
        thresholds[parameter] = float(value)
    return thresholds


def _thresholds_match(actual: dict[str, float] | None, expected: dict[str, float]) -> bool:
    return isinstance(actual, dict) and all(
        abs(actual[name] - expected[name]) <= 1e-12 for name in expected
    )


def _handle_detect(payload: dict, session_id: str) -> None:
    cwd_root = _cwd_root(payload)
    cwd_markers = _markers_for_root(cwd_root)
    run = _read_json(os.path.join(cwd_markers, RUN_MARKER))
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    requested_root = _canonical_root(tool_input.get("root", "."), cwd_root)
    result = _extract_detect_result(payload.get("tool_response"))
    detected_root = (
        _canonical_root(result.get("root"), cwd_root)
        if isinstance(result, dict) and result.get("root")
        else None
    )

    routed_root = cwd_root
    explicit_root = False
    run_active = isinstance(run, dict) and run.get("session_id") == session_id
    if run_active and isinstance(run.get("projectRoot"), str):
        routed_root = _canonical_root(run["projectRoot"], cwd_root)
        explicit_root = run.get("projectRootExplicit") is True

    # 새 detect 호출은 이전 allowlist를 무효화한다. 잘못된 root/응답/임계값으로
    # 호출되더라도 같은 세션의 오래된 detect 증거가 남아서는 안 된다.
    for root in {routed_root, requested_root}:
        try:
            os.remove(os.path.join(_markers_for_root(root), DETECT_MARKER))
        except OSError:
            pass

    root_matches = (
        run_active
        and isinstance(result, dict)
        and detected_root == requested_root
        and (not explicit_root or requested_root == routed_root)
    )
    if not root_matches:
        _allow()
        return

    route_changed = requested_root != routed_root
    if route_changed:
        _clear_invocation_markers(_markers_for_root(requested_root))

    route = {"projectRoot": requested_root, "projectRootExplicit": True}
    for root in {cwd_root, requested_root}:
        _write_marker(
            os.path.join(_markers_for_root(root), RUN_MARKER),
            session_id,
            route,
        )

    actual_thresholds = _requested_coverage_thresholds(tool_input)
    expected_thresholds = _expected_coverage_thresholds(requested_root)
    coverage_bound = _thresholds_match(actual_thresholds, expected_thresholds)
    allowed = _allowed_stub_artifacts(result, allow_coverage_stub=coverage_bound)
    marker_path = os.path.join(_markers_for_root(requested_root), DETECT_MARKER)
    if allowed:
        _write_marker(
            marker_path,
            session_id,
            {
                "tool_use_id": payload.get("tool_use_id"),
                "root": requested_root,
                "recommendedEntryStage": result.get("recommendedEntryStage"),
                "coverageThresholds": actual_thresholds,
                "expectedCoverageThresholds": expected_thresholds,
                "coverageThresholdsMatch": coverage_bound,
                "allowedArtifacts": allowed,
            },
        )
    else:
        try:
            os.remove(marker_path)
        except OSError:
            pass
    _allow()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — fail open on malformed hook input
        _allow()
        return 0

    try:
        tool_name = str(payload.get("tool_name", ""))
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        session_id = str(payload.get("session_id", ""))

        if tool_name == "Skill":
            _handle_skill(payload, tool_input, session_id)
        elif tool_name in ("Task", "Agent"):
            _handle_spawn(payload, tool_input, session_id)
        elif tool_name.endswith("detect_pipeline_state"):
            _handle_detect(payload, session_id)
        else:
            _allow()
        return 0
    except Exception:  # noqa: BLE001 — a guard must never break the session
        _allow()
        return 0


if __name__ == "__main__":
    sys.exit(main())
