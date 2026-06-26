#!/usr/bin/env python3
"""guard-network.py

PreToolUse Bash hook for the Spring Test Harness plugin.

Reads Claude Code hook JSON from stdin, inspects the Bash command, and
denies (or asks) if the command contains network-access utilities while
SPRING_TEST_HARNESS_NETWORK != "on".

Hook JSON input (Claude Code PreToolUse contract):
  {
    "tool_name": "Bash",
    "tool_input": { "command": "<shell command string>" },
    ...
  }

Hook JSON output (Claude Code hook decision contract):
  Allow:  {} or {"permissionDecision": "allow"}
  Deny:   {"permissionDecision": "deny", "message": "<reason>"}
  Ask:    {"permissionDecision": "ask",  "message": "<reason>"}

Network is considered OFF unless env var SPRING_TEST_HARNESS_NETWORK == "on".
Stdlib only (json, sys, os, re).
"""

import json
import os
import re
import sys

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
    re.compile(r'\bhost\b'),
    # Common patterns for inline network calls in build scripts
    re.compile(r'https?://'),
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
    return os.environ.get("SPRING_TEST_HARNESS_NETWORK", "").lower() == "on"


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
        print(json.dumps({"permissionDecision": "allow"}))
        return

    # Network call detected and network is off — deny with explanation
    decision = {
        "permissionDecision": "deny",
        "message": (
            "spring-test-harness: Network access is disabled by default. "
            "The command appears to make a network call. "
            "Set SPRING_TEST_HARNESS_NETWORK=on to permit network access, "
            "or remove the network call from the command."
        ),
    }
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
