#!/usr/bin/env python3
r"""guard-network.py

PreToolUse Bash hook for the Spring Test Harness plugin.

Reads Claude Code hook JSON from stdin, inspects the Bash command, and
denies (or asks) if the command contains network-access utilities while
TEST_AUTOEVERMATION_HARNESS_NETWORK != "on".

v0.22.1: **run-active scoped**. This guard only intervenes while a full-pipeline
run is active for the current session (``_workspace/.markers/run.json`` written
by ``record-run-context.py`` with a matching ``session_id``). Outside an active
run — e.g. a developer manually editing/committing/pushing this plugin's own
source, or any ordinary Bash session in a project that merely has this plugin
enabled — network commands are allowed unconditionally. This mirrors the
run-active scoping used for Zone B/C of ``guard-gate-artifacts.py``: the guard's
threat model is unsupervised subagents exfiltrating data or touching remote
state *during pipeline execution*, not human-directed manual sessions.

Hook JSON input (Claude Code PreToolUse contract):
  {
    "tool_name": "Bash",
    "tool_input": { "command": "<shell command string>" },
    "session_id": "...", "cwd": "...",
    ...
  }

Hook JSON output (Claude Code PreToolUse decision contract — the decision MUST be
nested under ``hookSpecificOutput``; a top-level ``permissionDecision`` key is not
part of the hook schema and is silently ignored, i.e. fails open):
  Allow:  {} (no opinion — defer to the normal permission flow) or
          {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "allow"}}
  Deny:   {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny",
                                  "permissionDecisionReason": "<reason>"}}

Decision table:
  * not Bash / no command / no network pattern match   -> allow
  * TEST_AUTOEVERMATION_HARNESS_NETWORK == "on"         -> allow (explicit opt-in)
  * no active run for this session (no matching
    _workspace/.markers/run.json)                       -> allow (manual/dev session)
  * active run + network pattern + network off          -> deny

Network is considered OFF unless env var TEST_AUTOEVERMATION_HARNESS_NETWORK == "on".
Stdlib only (json, sys, os, re).
"""

import json
import os
import re
import sys

MARKERS_DIR = ".markers"
RUN_MARKER = "run.json"

# ---------------------------------------------------------------------------
# Network-access command patterns
# ---------------------------------------------------------------------------
_NETWORK_PATTERNS = [
    re.compile(r'\bcurl\b'),
    re.compile(r'\bwget\b'),
    re.compile(r'\bnc\b'),           # netcat
    re.compile(r'\bnetcat\b'),
    re.compile(r'\bssh\b'),
    re.compile(r'\bscp\b'),
    re.compile(r'\bsftp\b'),
    re.compile(r'\bftp\b'),
    re.compile(r'\btelnet\b'),
    re.compile(r'\bnmap\b'),
    re.compile(r'\bdig\b'),
    re.compile(r'\bnslookup\b'),
    # NOTE: a bare \bhost\b pattern was removed — "host" appears in legitimate
    # non-network arguments (JDBC URLs, -Dspring.datasource.host, testcontainers
    # config) and over-blocked builds. The dig/nslookup DNS tools above remain.
    # Windows-native network tools (PowerShell/cmd) — curl.exe/wget.exe는 위의
    # \bcurl\b/\bwget\b 패턴이 이미 매칭한다.
    re.compile(r'\binvoke-webrequest\b', re.IGNORECASE),
    re.compile(r'\binvoke-restmethod\b', re.IGNORECASE),
    re.compile(r'\biwr\b', re.IGNORECASE),
    re.compile(r'\birm\b', re.IGNORECASE),
    re.compile(r'\bcertutil\b.*-urlcache', re.IGNORECASE),
    re.compile(r'\bbitsadmin\b', re.IGNORECASE),
    re.compile(r'\bstart-bitstransfer\b', re.IGNORECASE),
    re.compile(r'\bnet\.webclient\b', re.IGNORECASE),
    # Network verbs that fetch remote resources. A bare https?:// URL string in
    # an argument (e.g. -Dwiremock.url=http://localhost:8089) is NOT itself a
    # network call, so URLs are only denied in combination with a fetch verb —
    # the curl/wget/iwr patterns above already cover those. The verbs below
    # cover the remaining common fetchers.
    re.compile(r'\bgit\s+(clone|fetch|pull|push|ls-remote)\b'),
    re.compile(r'\burlopen\b'),
    re.compile(r'\brequests\.(get|post|put|delete|head)\b'),
    re.compile(r'--network'),
]


def _contains_network_call(command: str) -> bool:
    """Return True if command appears to make a network call."""
    for pattern in _NETWORK_PATTERNS:
        if pattern.search(command):
            return True
    return False


def _network_allowed() -> bool:
    """Return True if the harness network flag is explicitly set to on."""
    return os.environ.get("TEST_AUTOEVERMATION_HARNESS_NETWORK", "").lower() == "on"


def _run_active(payload: dict) -> bool:
    """Return True if this session has an active full-pipeline run (matching
    _workspace/.markers/run.json session_id, written by record-run-context.py)."""
    cwd = str(payload.get("cwd") or os.getcwd()).replace("\\", "/")
    session_id = str(payload.get("session_id", ""))
    marker_path = os.path.join(cwd, "_workspace", MARKERS_DIR, RUN_MARKER)
    try:
        with open(marker_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 — no marker / unreadable => not active
        return False
    return isinstance(data, dict) and data.get("session_id") == session_id


def _decision(decision: str, reason: str = "") -> None:
    """Emit a PreToolUse decision in the schema Claude Code actually honors."""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def main():
    # Read hook payload from stdin
    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # If we cannot parse the payload, allow the tool to proceed
        # (fail open on malformed input rather than blocking all Bash calls)
        print(json.dumps({}))
        return

    tool_name = payload.get("tool_name", "")
    if tool_name != "Bash":
        # Not a Bash call — allow
        print(json.dumps({}))
        return

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        print(json.dumps({}))
        return

    if not _contains_network_call(command):
        # No network indicators — allow
        print(json.dumps({}))
        return

    if _network_allowed():
        # Network explicitly permitted by env var
        _decision("allow")
        return

    if not _run_active(payload):
        # No active full-pipeline run for this session — manual/dev session,
        # the guard's threat model (unsupervised subagent network calls during
        # pipeline execution) does not apply.
        print(json.dumps({}))
        return

    # Active pipeline run + network call detected + network off — deny
    _decision(
        "deny",
        "test-autoevermation-harness-plugin: Network access is disabled by default "
        "during an active full-pipeline run. "
        "The command appears to make a network call. "
        "Set TEST_AUTOEVERMATION_HARNESS_NETWORK=on to permit network access, "
        "or remove the network call from the command.",
    )


if __name__ == "__main__":
    main()
