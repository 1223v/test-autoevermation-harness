#!/usr/bin/env python3
r"""record-run-context.py

PreToolUse hook (matcher: ``Skill|Task|Agent``) + PostToolUse hook
(matcher: ``*detect_pipeline_state``) for the Spring Test Harness plugin.

full-pipeline 실행의 **물리 강제(위임 계약)**를 위한 실행 컨텍스트 기록자.
guard-gate-artifacts.py가 판정에 사용하는 마커를 ``_workspace/.markers/``에 남긴다:

  * ``run.json``                        — full-pipeline Skill 호출 시 기록.
                                          {"session_id", "ts"}. 이 세션이 "하네스
                                          활성(run-active)"임을 나타내는 유일한 신호.
  * ``spawn-<subagent_type>.json``      — Task/Agent 스폰 시 기록. {"session_id", "ts"}.
                                          "해당 단계가 실제로 위임되었다"는 물리 증거.
  * ``pipeline-state.detected.json``    — detect_pipeline_state 호출 성공 후 기록.
                                          durable-resume stub 기록의 전제 조건.

Decision table:
  PreToolUse Skill:
    * full-pipeline 아님                        -> allow (무동작)
    * full-pipeline                             -> 부수효과: 이전 세션 마커 청소 +
                                                   run.json 기록; allow +
                                                   additionalContext(단계 계약 요약)
  PreToolUse Task|Agent:
    * subagent_type == test-code-generator      -> run 활성인데 04_scenario_set.json
                                                   또는 04b_approval.json 부재면 deny
                                                   (4.5 승인 게이트 선행 — 스폰 시점 차단);
                                                   아니면 spawn 마커 기록 후 allow
    * 그 외 subagent_type                        -> spawn 마커 기록 후 allow
  PostToolUse detect_pipeline_state             -> pipeline-state.detected.json 기록; allow
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
    "mutation-analyst",
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


def _workspace_root(payload: dict) -> str:
    cwd = str(payload.get("cwd") or os.getcwd()).replace("\\", "/")
    return os.path.join(cwd, "_workspace")


def _markers_dir(payload: dict) -> str:
    return os.path.join(_workspace_root(payload), MARKERS_DIR)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _write_marker(path: str, session_id: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"session_id": session_id, "ts": time.time()}, fh)


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


def _handle_skill(payload: dict, tool_input: dict, session_id: str) -> None:
    skill_name = str(
        tool_input.get("skill") or tool_input.get("name") or tool_input.get("command") or ""
    )
    if "full-pipeline" not in skill_name:
        _allow()
        return

    markers = _markers_dir(payload)
    run_path = os.path.join(markers, RUN_MARKER)
    existing = _read_json(run_path)
    if not (isinstance(existing, dict) and existing.get("session_id") == session_id):
        # 새 세션의 run 시작: 이전 세션 스폰/감지 증거는 무효 → 청소
        try:
            if os.path.isdir(markers):
                for entry in os.listdir(markers):
                    if entry.startswith("spawn-") or entry == DETECT_MARKER:
                        try:
                            os.remove(os.path.join(markers, entry))
                        except OSError:
                            pass
        except OSError:
            pass
    _write_marker(run_path, session_id)
    _allow_with_context(_STAGE_CONTRACT_REMINDER)


def _handle_spawn(payload: dict, tool_input: dict, session_id: str) -> None:
    agent_type = _normalize_agent_type(tool_input.get("subagent_type") or "")
    if agent_type not in PIPELINE_AGENTS:
        _allow()
        return

    markers = _markers_dir(payload)
    workspace = _workspace_root(payload)

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


def _handle_detect(payload: dict, session_id: str) -> None:
    _write_marker(os.path.join(_markers_dir(payload), DETECT_MARKER), session_id)
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
