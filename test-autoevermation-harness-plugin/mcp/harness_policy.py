"""Shared execution policy and durable, controller-owned correction budget.

No SDK dependency. `resolve` reads {request, saved} from stdin; `budget` reads
the project's saved config. Both hosts use the same CLI through launch.cjs.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import sys

from harness_runtime import atomic_json, scoped_path

PROFILES = {
    "fast": ({"line": .80, "branch": .70, "method": .80, "class": 1.0}, 1),
    "balanced": ({"line": .90, "branch": .80, "method": .90, "class": 1.0}, 3),
    "strict": ({"line": .95, "branch": .90, "method": .95, "class": 1.0}, None),
}
DEFAULT_EXCLUDES = ["**/*Application*", "**/config/**", "**/dto/**", "**/generated/**"]
REASONS = {"test-failure", "conformance", "coverage"}


def execution_policy(config: dict) -> dict:
    raw = config.get("executionPolicy", {})
    if not isinstance(raw, dict):
        raise ValueError("INVALID_EXECUTION_POLICY")
    profile = raw.get("profile", "strict")
    if profile not in PROFILES:
        raise ValueError("INVALID_EXECUTION_PROFILE")
    cap = raw.get("maxAutoFixRounds", PROFILES[profile][1])
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise ValueError("INVALID_AUTO_FIX_BUDGET")
    if profile != "strict" and cap is None:
        raise ValueError("BOUNDED_PROFILE_REQUIRES_BUDGET")
    if raw.get("delegation", "auto") != "auto":
        raise ValueError("INVALID_DELEGATION_POLICY")
    return {"profile": profile, "maxAutoFixRounds": cap, "delegation": "auto"}


def resolve_config(request: dict, saved: dict | None = None) -> dict:
    """Explicit mode selection replaces only profile defaults, never exclusions.

    Without a selection, saved custom thresholds and legacy iteration semantics
    survive. New interactive callers ask for a profile before calling this.
    """
    saved = saved or {}
    result = deepcopy(saved)
    result.update(deepcopy(request))
    selected = request.get("executionPolicy", {})
    if not isinstance(selected, dict):
        raise ValueError("INVALID_EXECUTION_POLICY")
    explicit_profile = "profile" in selected
    raw_policy = ({} if explicit_profile else deepcopy(saved.get("executionPolicy") or {}))
    raw_policy.update(selected)
    policy = execution_policy({"executionPolicy": raw_policy})
    coverage = dict(PROFILES[policy["profile"]][0])
    if not explicit_profile:
        coverage.update(saved.get("coverage") or {})
    elif "excludes" in (saved.get("coverage") or {}):
        coverage["excludes"] = deepcopy(saved["coverage"]["excludes"])
    coverage.update(request.get("coverage") or {})
    coverage.setdefault("excludes", list(DEFAULT_EXCLUDES))
    for key in ("line", "branch", "method", "class"):
        value = coverage[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("INVALID_COVERAGE_THRESHOLD: " + key)
    result["schemaVersion"] = 2
    result["coverage"] = coverage
    # Do not silently migrate old configuration or change its fingerprint.
    if raw_policy or "executionPolicy" in saved or "executionPolicy" in request:
        result["executionPolicy"] = policy
    return result


def budget_summary(config: dict, state: dict | None = None) -> dict:
    policy = execution_policy(config)
    state = state or {}
    rounds = state.get("rounds", [])
    cap = policy["maxAutoFixRounds"]
    allowance = state.get("extraRounds", 0)
    if (isinstance(allowance, bool) or not isinstance(allowance, int) or allowance < 0
            or not isinstance(rounds, list)
            or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"]
                   or r.get("reason") not in REASONS or not isinstance(r.get("validated"), bool)
                   for r in rounds)):
        raise ValueError("INVALID_BUDGET_STATE")
    if len({r["id"] for r in rounds}) != len(rounds) or sum(not r["validated"] for r in rounds) > 1:
        raise ValueError("INVALID_BUDGET_STATE")
    remaining = None if cap is None else max(0, cap + allowance - len(rounds))
    pending = next((r["id"] for r in rounds if not r.get("validated")), None)
    return {**policy, "autoFixRounds": len(rounds), "remainingRounds": remaining,
            "pendingRound": pending, "canAutoFix": pending is None and remaining != 0,
            "stopReason": "VALIDATION_REQUIRED" if pending else "AUTO_FIX_BUDGET_EXHAUSTED" if remaining == 0 else None}


@contextmanager
def _budget_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def update_budget(root: str, action: str = "status", round_id: str = "",
                  reason: str = "", authorization: str = "") -> dict:
    """Reserve BEFORE a correction; complete AFTER its verification.

    Retries of a round id are idempotent. Restarting a host or full-pipeline does
    not reset this file. Only explicit new-task/continue authorization does.
    Controller alone calls this function; workers receive the reserved id.
    """
    root = str(Path(root).resolve())
    config = json.loads(scoped_path(root, "_workspace/00_config-harness.json").read_text(encoding="utf-8"))
    execution_policy(config)
    path = scoped_path(root, "_workspace/execution-budget.json")

    def read_state():
        if not path.exists():
            if action != "new-task" and execution_policy(config)["maxAutoFixRounds"] is not None:
                for name, fields in (("07_repair_result.json", ("retryCount", "fixed", "patches")),
                                     ("08_coverage_result.json", ("iterations",)),
                                     ("09b_conformance_repair.json", ("rounds", "fixed", "regenerated"))):
                    previous = scoped_path(root, "_workspace/" + name)
                    if previous.is_file():
                        data = json.loads(previous.read_text(encoding="utf-8"))
                        if any(data.get(field) for field in fields):
                            raise ValueError("BUDGET_STATE_REQUIRED")
            return {"schemaVersion": 2, "root": root, "rounds": [], "extraRounds": 0, "authorizations": []}
        state = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(state, dict) or state.get("schemaVersion") != 2 or state.get("root") != root
                or not isinstance(state.get("rounds"), list) or not isinstance(state.get("authorizations"), list)
                or any(not isinstance(value, str) for value in state["authorizations"])):
            raise ValueError("INVALID_BUDGET_STATE")
        return state

    if action == "status":
        return budget_summary(config, read_state())
    with _budget_lock(path.with_suffix(".lock")):
        state = read_state()
        summary = budget_summary(config, state)
        if action == "reserve":
            if not round_id or reason not in REASONS:
                raise ValueError("ROUND_ID_AND_REASON_REQUIRED")
            existing = next((r for r in state["rounds"] if r["id"] == round_id), None)
            if existing:
                if existing["reason"] != reason:
                    raise ValueError("ROUND_ID_CONFLICT")
                return {**summary, "reserved": not existing["validated"], "reusedReservation": True}
            if not summary["canAutoFix"]:
                return {**summary, "reserved": False}
            state["rounds"].append({"id": round_id, "reason": reason, "validated": False})
        elif action == "complete":
            entry = next((r for r in state["rounds"] if r["id"] == round_id), None)
            if entry is None:
                raise ValueError("UNKNOWN_CORRECTION_ROUND")
            entry["validated"] = True
        elif action in {"continue", "new-task"}:
            if not authorization.strip():
                raise ValueError("EXPLICIT_USER_AUTHORIZATION_REQUIRED")
            key = hashlib.sha256((action + authorization).encode()).hexdigest()
            if key not in state["authorizations"]:
                if summary["pendingRound"]:
                    raise ValueError("VALIDATION_REQUIRED")
                if action == "new-task":
                    state["rounds"], state["extraRounds"] = [], 0
                else:
                    state["extraRounds"] += execution_policy(config)["maxAutoFixRounds"] or 0
                state["authorizations"].append(key)
        else:
            raise ValueError("INVALID_BUDGET_ACTION")
        atomic_json(path, state)
        return {**budget_summary(config, state), "reserved": action == "reserve"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resolve", "budget"))
    parser.add_argument("--root")
    parser.add_argument("--action", default="status", choices=("status", "reserve", "complete", "continue", "new-task"))
    parser.add_argument("--round-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--authorization", default="")
    args = parser.parse_args()
    try:
        if args.command == "resolve":
            data = json.load(sys.stdin)
            result = resolve_config(data.get("request", {}), data.get("saved"))
        else:
            if not args.root:
                raise ValueError("PROJECT_ROOT_REQUIRED")
            result = update_budget(args.root, args.action, args.round_id, args.reason, args.authorization)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
