#!/usr/bin/env python3
"""collect-test-reports.py

Find and parse JUnit XML test reports produced by Gradle or Maven, then emit
a TestRunResult JSON to stdout.

Gradle report location : build/test-results/test/*.xml
Maven report location  : target/surefire-reports/*.xml

Failure classification:
  TEST_COMPILE_FAILED  — error message contains compile/compilation clues
  FLAKY_SUSPECTED      — test name already passed in the same run (not applicable
                         at single-run parse time) OR message contains timing/
                         concurrency keywords
  TEST_RUNTIME_FAILED  — everything else

Usage:
  python3 collect-test-reports.py [projectRoot]
  projectRoot defaults to cwd.

Output: JSON to stdout matching TestRunResult schema.
Exit code: 0 always (failures are reported inside the JSON, not via exit code).
"""

import json
import sys
import os
import glob
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Heuristic keywords for failure classification
# ---------------------------------------------------------------------------
_COMPILE_KEYWORDS = (
    "compilationerror",
    "compilation error",
    "cannot find symbol",
    "does not exist",
    "package does not",
    "symbol not found",
    "javac",
    "compilejavateststestjava",
    "compiletestjava",
)

_FLAKY_KEYWORDS = (
    "timeout",
    "timed out",
    "flaky",
    "race condition",
    "concurrentmodification",
    "socketexception",
    "connectionrefused",
    "connection refused",
    "intermittent",
)


def _classify(failure_type: str, message: str) -> str:
    """Return one of TEST_COMPILE_FAILED | FLAKY_SUSPECTED | TEST_RUNTIME_FAILED."""
    combined = (failure_type + " " + message).lower()
    for kw in _COMPILE_KEYWORDS:
        if kw in combined:
            return "TEST_COMPILE_FAILED"
    for kw in _FLAKY_KEYWORDS:
        if kw in combined:
            return "FLAKY_SUSPECTED"
    return "TEST_RUNTIME_FAILED"


def _find_report_dirs(root: str):
    """Return a list of (glob_pattern, existing_paths) tuples."""
    candidates = [
        os.path.join(root, "build", "test-results", "test", "*.xml"),
        os.path.join(root, "target", "surefire-reports", "*.xml"),
        # Support multi-module: search one level deeper
        os.path.join(root, "*", "build", "test-results", "test", "*.xml"),
        os.path.join(root, "*", "target", "surefire-reports", "*.xml"),
    ]
    found = []
    for pattern in candidates:
        matches = glob.glob(pattern)
        found.extend(matches)
    return found


def _parse_xml_file(path: str):
    """Parse a single JUnit XML file; return (passed_count, failures[])."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return 0, [{"test": path, "type": "TEST_RUNTIME_FAILED",
                    "message": f"XML parse error: {exc}"}]

    root_el = tree.getroot()

    # Handle both <testsuite> root and <testsuites><testsuite> wrapping
    suites = []
    if root_el.tag == "testsuites":
        suites = list(root_el.findall("testsuite"))
    elif root_el.tag == "testsuite":
        suites = [root_el]
    else:
        suites = list(root_el.iter("testsuite"))

    passed = 0
    failures = []

    for suite in suites:
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}.{name}" if classname else name

            failure_el = tc.find("failure")
            error_el = tc.find("error")
            skipped_el = tc.find("skipped")

            if failure_el is not None or error_el is not None:
                el = failure_el if failure_el is not None else error_el
                ftype = el.get("type", "")
                fmsg = el.get("message", "") or (el.text or "")
                failures.append({
                    "test": test_id,
                    "type": _classify(ftype, fmsg),
                    "message": fmsg[:500],  # truncate very long messages
                })
            elif skipped_el is None:
                passed += 1

    return passed, failures


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

    xml_paths = _find_report_dirs(root)

    total_passed = 0
    all_failures = []

    for xml_path in xml_paths:
        p, f = _parse_xml_file(xml_path)
        total_passed += p
        all_failures.extend(f)

    # Deduplicate report directory paths
    report_dirs = sorted({os.path.dirname(p) for p in xml_paths})

    if not xml_paths:
        overall_status = "failed"
    elif all_failures:
        overall_status = "partial"
    else:
        overall_status = "ok"

    result = {
        "status": overall_status,
        "passed": total_passed,
        "failed": all_failures,
        "reportPaths": report_dirs,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
