#!/usr/bin/env python3
"""guard-read.py

PreToolUse hook for the Spring Test Harness plugin (matcher: ``Read|WebFetch``).

Restores the security posture that the plugin's ``settings.json`` *describes* but
that Claude Code does not actually apply (per the plugin reference, a plugin
``settings.json`` only honors the ``agent``/``subagentStatusLine`` keys — its
``permissions``/``env`` blocks are ignored). The reliable enforcement point for a
plugin is a hook, so this mirrors the intended denies via the hook contract:

  * ``WebFetch`` — denied while the network is OFF (default). Set
    ``SPRING_TEST_HARNESS_NETWORK=on`` to permit.
  * ``Read`` of secret / vendor / build-output paths — denied
    (``.env``, ``*.pem``, ``secrets/``, ``build/``, ``target/``, ``node_modules/``).

Hook JSON input (Claude Code PreToolUse contract):
  { "tool_name": "Read"|"WebFetch", "tool_input": { "file_path": "..." }, ... }

Hook JSON output (decision contract):
  Allow:  {}
  Deny:   {"permissionDecision": "deny", "message": "<reason>"}

Stdlib only (json, sys, os, re, fnmatch). Fails open on malformed input.
"""

import fnmatch
import json
import os
import sys

# Deny-globs for Read (matched against the absolute and normalized path). These
# mirror settings.json's `permissions.deny` Read rules, which are the documented
# intent but are not enforced by Claude Code for plugin-provided settings.json.
_READ_DENY_GLOBS = [
    "*/.env",
    ".env",
    "*.pem",
    "*/secrets/*",
    "*/build/*",
    "*/target/*",
    "*/node_modules/*",
]


def _network_allowed() -> bool:
    """Network is OFF unless explicitly enabled (matches guard-network.py)."""
    return os.environ.get("SPRING_TEST_HARNESS_NETWORK", "").lower() == "on"


def _read_denied(path: str) -> bool:
    """True if a Read path matches a denied secret/vendor/build glob."""
    if not path:
        return False
    norm = path.replace("\\", "/")
    candidates = {norm}
    # Also test the basename so bare ".env"/"*.pem" globs match reliably.
    candidates.add(os.path.basename(norm))
    for glob in _READ_DENY_GLOBS:
        for cand in candidates:
            if fnmatch.fnmatch(cand, glob):
                return True
    # Segment-based fallback (handles paths without leading "*/").
    segments = norm.split("/")
    if any(seg in ("secrets", "build", "target", "node_modules") for seg in segments):
        return True
    return False


def _deny(message: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "message": message}))


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({}))  # fail open on malformed input
        return

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name == "WebFetch":
        if _network_allowed():
            print(json.dumps({"permissionDecision": "allow"}))
            return
        _deny(
            "spring-test-harness: WebFetch is disabled by default (network OFF). "
            "Set SPRING_TEST_HARNESS_NETWORK=on to permit network access."
        )
        return

    if tool_name == "Read":
        path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if _read_denied(path):
            _deny(
                "spring-test-harness: reading secret/vendor/build-output paths is "
                f"denied by default policy (path: {path}). Allowed source roots are "
                "src/main and src/test; build artifacts are parsed via the build-test "
                "MCP server, not the Read tool."
            )
            return
        print(json.dumps({}))
        return

    # Any other tool — allow.
    print(json.dumps({}))


if __name__ == "__main__":
    main()
