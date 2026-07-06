#!/usr/bin/env python3
"""guard-gate-artifacts.py

PreToolUse hook for the Spring Test Harness plugin (matcher: ``Write|Edit``).

Mechanically enforces the stage 8/9 gate contract (fallback-policy.md #21):
a coverage/mutation gate result that claims the gate FAILED but shows no
evidence the closing loop actually ran (``iterations < 1`` or an empty
remaining-gap report) is an invalid artifact — it means the orchestrator
skipped coverage-closer/mutation-analyst (e.g. citing an RA advisory as a
"structural coverage limit", which is never a sanctioned skip reason).

Guarded artifacts (matched by basename):
  * ``08_coverage_result.json``  — invariant on ``gatePassed``/``iterations``/
    ``remainingGaps`` (measure-coverage output schema)
  * ``09_mutation_result.json``  — invariant on ``thresholdMet``/``iterations``/
    ``survivingMutants`` (mutation-test output schema)

Decision table:
  * not a guarded file                      -> allow
  * Edit on a guarded file                  -> deny (content not verifiable;
                                               gate artifacts must be written
                                               whole via Write)
  * Write, content not valid JSON object    -> deny
  * ``status == "failed"``                  -> allow (tool-breakage path,
                                               reported via errors[])
  * gate passed (gatePassed/thresholdMet)   -> allow
  * gate failed without loop evidence       -> deny (#21)
  * anything malformed / internal error     -> allow (fail-open — a guard must
                                               never break the session)

Hook JSON input (Claude Code PreToolUse contract):
  { "tool_name": "Write"|"Edit", "tool_input": { "file_path": "...",
    "content": "..." (Write) }, ... }

Hook JSON output (decision contract):
  Allow:  {}
  Deny:   {"permissionDecision": "deny", "message": "<reason>"}

Stdlib only (json, sys, os). Fails open on malformed input.
"""

import json
import os
import sys

COVERAGE_ARTIFACT = "08_coverage_result.json"
MUTATION_ARTIFACT = "09_mutation_result.json"

_CONTRACT_HINT = (
    "(fallback-policy.md #21) 게이트 미달 시 coverage-closer/mutation-analyst "
    "루프를 실제 수행한 뒤 잔여를 전량 보고하고 기록하라. RA advisory는 "
    "8·9단계 게이트의 면제·스킵 사유가 아니며, '구조적 커버리지 한계' 판단은 "
    "에이전트의 remainingGaps[].reason/survivingMutants[]로만 성립한다. "
    "스코프 제외는 HarnessConfig.coverage.excludes(사용자 승인)로만 가능하다."
)


def _deny(message: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "message": message}, ensure_ascii=False))


def _allow() -> None:
    print(json.dumps({}))


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


def _check_mutation(data: dict) -> str:
    """Return a deny message for an invalid 09 artifact, or '' to allow."""
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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — fail open on malformed hook input
        _allow()
        return 0

    try:
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        file_path = str(tool_input.get("file_path", ""))
        basename = os.path.basename(file_path.replace("\\", "/"))

        if basename not in (COVERAGE_ARTIFACT, MUTATION_ARTIFACT):
            _allow()
            return 0

        if tool_name == "Edit":
            _deny(
                "게이트 산출물(%s)은 Edit로 부분 수정할 수 없다 — 무효 조건 검증이 "
                "불가하므로 Write로 전체를 기록하라. %s" % (basename, _CONTRACT_HINT)
            )
            return 0

        content = tool_input.get("content")
        try:
            data = json.loads(content)
        except Exception:  # noqa: BLE001
            data = None
        if not isinstance(data, dict):
            _deny(
                "게이트 산출물(%s)이 유효한 JSON 객체가 아니다 — measure-coverage/"
                "mutation-test 출력 스키마로 기록하라." % basename
            )
            return 0

        message = _check_coverage(data) if basename == COVERAGE_ARTIFACT else _check_mutation(data)
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
