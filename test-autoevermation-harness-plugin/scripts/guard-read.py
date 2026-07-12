#!/usr/bin/env python3
"""guard-read.py

PreToolUse hook for the Spring Test Harness plugin (matcher: ``Read|WebFetch``).

Restores the security posture that the plugin's ``settings.json`` *describes* but
that Claude Code does not actually apply (per the plugin reference, a plugin
``settings.json`` only honors the ``agent``/``subagentStatusLine`` keys — its
``permissions``/``env`` blocks are ignored). The reliable enforcement point for a
plugin is a hook, so this mirrors the intended denies via the hook contract:

  * ``WebFetch`` — denied while the network is OFF (default). Set
    ``TEST_AUTOEVERMATION_HARNESS_NETWORK=on`` to permit.
  * ``Read`` of secret / vendor / build-output paths — denied
    (``.env``, ``*.pem``, ``secrets/``, ``build/``, ``target/``, ``node_modules/``).

Hook JSON input (Claude Code PreToolUse contract):
  { "tool_name": "Read"|"WebFetch", "tool_input": { "file_path": "..." }, ... }

Hook JSON output (Claude Code PreToolUse decision contract — the decision MUST be
nested under ``hookSpecificOutput``; a top-level ``permissionDecision`` key is not
part of the hook schema and is silently ignored, i.e. fails open):
  Allow:  {} (no opinion) or
          {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "allow"}}
  Deny:   {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny",
                                  "permissionDecisionReason": "<reason>"}}

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
    "*/node_modules/*",
]
# NOTE: build/target are NOT plain globs — "build"/"target" are legal Java package
# directory names under src/ (e.g. src/main/java/com/example/build/Foo.java).
# They are denied only as build-OUTPUT roots, i.e. when no "src" segment precedes
# them in the path. See _read_denied().


def _network_allowed() -> bool:
    """Network is OFF unless explicitly enabled (matches guard-network.py)."""
    return os.environ.get("TEST_AUTOEVERMATION_HARNESS_NETWORK", "").lower() == "on"


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
    segments = [seg for seg in norm.split("/") if seg]
    if any(seg in ("secrets", "node_modules") for seg in segments):
        return True
    # build/target: deny only as build-OUTPUT roots. A build/target segment that
    # sits below a src/ tree is a legal Java package directory, not build output.
    for idx, seg in enumerate(segments):
        if seg in ("build", "target") and "src" not in segments[:idx]:
            return True
    return False


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


def _deny(message: str) -> None:
    _decision("deny", message)


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
            _decision("allow")
            return
        _deny(
            "test-autoevermation-harness-plugin: WebFetch is disabled by default (network OFF). "
            "Set TEST_AUTOEVERMATION_HARNESS_NETWORK=on to permit network access."
        )
        return

    if tool_name == "Read":
        path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if _read_denied(path):
            _deny(
                "test-autoevermation-harness-plugin: reading secret/vendor/build-output paths is "
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
