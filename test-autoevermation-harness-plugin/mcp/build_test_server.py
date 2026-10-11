#!/usr/bin/env python3
"""build_test_server.py — REAL build-test MCP server (coverage-aware engine).

MCPServer server named "build-test". Coverage-aware test execution engine for
the Spring test-harness plugin.

Design source of truth:
  - RESEARCH_NOTES.md  (§1 MCPServer API, §3 JaCoCo 0.8.12, §6 near-100% policy;
                        build-test-mcp design + TestRunResult schema)
  - Build-tool detection and JUnit/JaCoCo report parsing are implemented inline.

Exposed surface: ``@mcp.tool()`` ONLY. v0.33.0 deleted the ``build://metadata`` /
``build://test-reports`` resources and the ``suggest_test_command`` prompt — they were
MCPServer boilerplate (RESEARCH_NOTES §1) that no agent could reach (no
``ReadMcpResourceTool`` in any agent's tool list) and that duplicated
``detect_build_tool`` / ``parse_junit_xml`` / ``run_targeted_tests`` in a worse form.
The prompt had also drifted: it hardcoded ``-o``/``--offline`` while the real path gates
that flag on ``_network_allowed()``. Do not re-add resources/prompts here.

Standard library only (subprocess, xml.etree, json, os, shlex). Python 3.10+.

Security posture (RESEARCH_NOTES §build-test-mcp, §권한과 보안):
  - All shell arguments are shlex-quoted.
  - Targeted/narrowest test scope by default.
  - Dependency resolution is offline by default (not an OS network sandbox) unless
    BUILD_TEST_ALLOW_NETWORK=1 is set in the environment.
"""

from __future__ import annotations

import glob
import fnmatch
import hashlib
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_runtime import atomic_json, file_digest, runtime_info, scoped_path, stop_process_tree

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:  # clearer startup diagnostic than a raw traceback
    import sys

    sys.stderr.write(
        "test-autoevermation-harness-plugin build-test: the 'mcp' package is not importable by this "
        f"interpreter ({sys.executable}).\n"
        "Install it into the SAME python3 that Claude Code launches:\n"
        "  python3 -m pip install -r mcp/requirements.txt\n"
        f"(original error: {exc})\n"
    )
    raise

mcp = MCPServer("build-test")

# ---------------------------------------------------------------------------
# Constants / policy defaults
# ---------------------------------------------------------------------------

# Default coverage gate thresholds (RESEARCH_NOTES §6 near-100% policy).
DEFAULT_LINE = 0.95
DEFAULT_BRANCH = 0.90
DEFAULT_METHOD = 0.95
DEFAULT_CLASS = 1.0

# Subprocess wall-clock cap (seconds) so a hung build can't block the server.
_RUN_TIMEOUT = 1800

# Failure-classification heuristics.
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


# ---------------------------------------------------------------------------
# Internal helpers (not exposed as tools)
# ---------------------------------------------------------------------------

def _network_allowed() -> bool:
    """Whether build dependency resolution may use the network (not process isolation)."""
    val = os.environ.get("BUILD_TEST_ALLOW_NETWORK", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _plugin_version() -> "str | None":
    """Best-effort read of the plugin's declared version, or None on failure.

    Reads .claude-plugin/plugin.json next to the plugin root (this file lives in
    mcp/). Never raises: any error degrades to None.
    """
    try:
        manifest = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".claude-plugin", "plugin.json",
        )
        with open(manifest, encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except Exception:
        return None


def _detect(root: str) -> dict:
    """Core build-tool detection. Returns {buildTool, wrapper} or BUILD_TOOL_UNDETECTED.

    Detection order: prefer the wrapper, then standard build files, Gradle before Maven.
    """
    if not os.path.isdir(root):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"directory not found: {root}"}

    tool = "none"
    wrapper = False

    def _has(*names: str) -> bool:
        return any(os.path.isfile(os.path.join(root, n)) for n in names)

    # gradlew.bat/mvnw.cmd: Gradle/Maven 래퍼의 Windows 배치 변형(공식 래퍼 산출물)
    if _has("gradlew", "gradlew.bat"):
        tool, wrapper = "gradle", True
    elif _has("build.gradle", "build.gradle.kts"):
        tool, wrapper = "gradle", False
    elif _has("mvnw", "mvnw.cmd"):
        tool, wrapper = "maven", True
    elif _has("pom.xml"):
        tool, wrapper = "maven", False

    if tool == "none":
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"no Gradle or Maven build files found in: {root}"}

    return {"status": "ok", "buildTool": tool, "wrapper": wrapper}


def _classify_failure(failure_type: str, message: str) -> str:
    """Return TEST_COMPILE_FAILED | FLAKY_SUSPECTED | TEST_RUNTIME_FAILED."""
    combined = (failure_type + " " + message).lower()
    for kw in _COMPILE_KEYWORDS:
        if kw in combined:
            return "TEST_COMPILE_FAILED"
    for kw in _FLAKY_KEYWORDS:
        if kw in combined:
            return "FLAKY_SUSPECTED"
    return "TEST_RUNTIME_FAILED"


# Report locations (each entry = path components under root; "*" = one submodule level).
_JUNIT_REL = (
    ("build", "test-results", "test", "*.xml"),
    ("target", "surefire-reports", "*.xml"),
    ("target", "failsafe-reports", "*.xml"),
    ("*", "build", "test-results", "test", "*.xml"),
    ("*", "target", "surefire-reports", "*.xml"),
    ("*", "target", "failsafe-reports", "*.xml"),
)
_JACOCO_REL = (
    ("build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
    ("target", "site", "jacoco", "jacoco.xml"),
    ("**", "build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
    ("**", "target", "site", "jacoco", "jacoco.xml"),
)


def _find_reports(root: str, candidates: tuple, recursive_name: str | None = None) -> list[str]:
    """Collect report paths matching any candidate (in order); "*" candidates are globbed,
    plain candidates matched by isfile. If none match and recursive_name is given, fall back
    to a recursive ``**/<recursive_name>`` search. Returns all matches (possibly empty)."""
    found: list[str] = []
    for rel in candidates:
        pat = os.path.join(root, *rel)
        if "*" in pat:
            found.extend(glob.glob(pat, recursive=True))
        elif os.path.isfile(pat):
            found.append(pat)
    if recursive_name:
        found.extend(glob.glob(os.path.join(root, "**", recursive_name), recursive=True))
    return list(dict.fromkeys(os.path.realpath(p) for p in found
                              if Path(p).resolve().is_relative_to(Path(root).resolve())
                              and "_workspace" not in Path(p).relative_to(root).parts))


def _find_junit_xml(root: str) -> list[str]:
    """JUnit testcase reports across configured tasks/modules (never summary XML)."""
    patterns = (
        ("**", "build", "test-results", "*", "TEST-*.xml"),
        ("**", "target", "surefire-reports", "TEST-*.xml"),
        ("**", "target", "failsafe-reports", "TEST-*.xml"),
    )
    return sorted({os.path.abspath(p) for rel in patterns
                   for p in glob.glob(os.path.join(root, *rel), recursive=True)})


# ---------------------------------------------------------------------------
# Staleness (durable-resume freshness)
#
# Durable evidence (JUnit/JaCoCo XML, approved scenario docs, a cached HarnessConfig)
# proves that a stage RAN ONCE — not that it ran against the CURRENT source. When the
# service code changes between runs, resuming on that evidence would report "all
# scenarios satisfied" without ever executing the changed code. These helpers give
# detect_pipeline_state a machine comparison (source mtime vs evidence mtime) so the
# resume decision can be made on freshness rather than mere existence.
# ---------------------------------------------------------------------------

# Source roots to scan, mirroring the one-submodule-level convention of _JUNIT_REL.
_SOURCE_REL = (
    ("src", "main", "java"),
    ("src", "test", "java"),
    ("**", "src", "main", "java"),
    ("**", "src", "test", "java"),
)

_BUILD_FILES = ("build.gradle", "build.gradle.kts", "pom.xml",
                "settings.gradle", "settings.gradle.kts", "gradle.properties")

# Filesystem timestamp granularity differs across platforms (HFS+/ext3 = 1s, FAT = 2s).
# Only treat evidence as stale when the source is newer by more than this margin, so a
# source and a report written in the same second are never mistaken for a code change.
_STALE_TOLERANCE_SEC = 2.0


def _newest_mtime(paths: list[str]) -> "tuple[float | None, list[str]]":
    """Return (newest mtime, paths sorted newest-first) — unreadable entries skipped."""
    stamped: list[tuple[float, str]] = []
    for p in paths:
        try:
            stamped.append((os.path.getmtime(p), p))
        except OSError:
            continue
    if not stamped:
        return None, []
    stamped.sort(reverse=True)
    return stamped[0][0], [p for _mt, p in stamped]


def _collect_source_files(root: str) -> list[str]:
    """All .java files under the project's source roots (root + one submodule level)."""
    files: list[str] = []
    for rel in _SOURCE_REL:
        pattern = os.path.join(root, *rel)
        bases = glob.glob(pattern, recursive=True) if "*" in pattern else (
            [pattern] if os.path.isdir(pattern) else []
        )
        for base in bases:
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, names in os.walk(base):
                files.extend(
                    os.path.join(dirpath, n) for n in names if n.endswith(".java")
                )
    return sorted(set(p for p in files if Path(p).resolve().is_relative_to(Path(root).resolve())
                      and "_workspace" not in Path(p).relative_to(root).parts))


def _is_newer(candidate: "float | None", reference: "float | None") -> bool:
    """True when `candidate` is newer than `reference` beyond the tolerance margin."""
    if candidate is None or reference is None:
        return False
    return candidate > reference + _STALE_TOLERANCE_SEC


def _compute_staleness(root: str) -> dict:
    """Compare newest source mtime against each piece of durable evidence.

    Every probe is fail-safe (same posture as detect_pipeline_state): an unreadable
    path yields None/False rather than raising, because freshness detection must never
    break the pipeline. A `None` on either side means "cannot compare" -> not stale,
    so a project without that evidence is never flagged.
    """
    source_mtime, source_paths = _newest_mtime(_collect_source_files(root))

    junit_mtime, _ = _newest_mtime(_find_junit_xml(root))
    jacoco_mtime, _ = _newest_mtime(_find_jacoco_xml_all(root))
    scenario_mtime, _ = _newest_mtime(
        glob.glob(os.path.join(root, "test_docs", "scenarios", "*.md"))
    )

    build_mtime, _ = _newest_mtime(
        [os.path.join(root, name) for name in _BUILD_FILES]
    )
    config_mtime, _ = _newest_mtime(
        [os.path.join(root, "_workspace", "00_config-harness.json")]
    )

    modules = _module_dirs(root)
    def stale_in_module(reports):
        for module in modules:
            own = lambda p: max((m for m in modules if Path(p).is_relative_to(Path(m))), key=len, default=root) == module
            source, _ = _newest_mtime([p for p in source_paths if own(p)])
            stamps = [os.path.getmtime(p) for p in reports if own(p)]
            if source is not None and stamps and any(_is_newer(source, stamp) for stamp in stamps):
                return True
        return False

    return {
        "sourceNewerThanJunit": stale_in_module(_find_junit_xml(root)),
        "sourceNewerThanJacoco": stale_in_module(_find_jacoco_xml_all(root)),
        "sourceNewerThanScenarios": _is_newer(source_mtime, scenario_mtime),
        "buildFileNewerThanConfig": _is_newer(build_mtime, config_mtime),
        "newestSourceMtime": source_mtime,
        "newestSourcePaths": source_paths[:10],
        "toleranceSeconds": _STALE_TOLERANCE_SEC,
    }


def _safe_parse_xml(path: str) -> tuple:
    """Parse an XML file; return (root_element, None) or (None, 'XML parse error: ...')."""
    try:
        return ET.parse(path).getroot(), None
    except (ET.ParseError, OSError, ValueError) as exc:
        return None, f"XML parse error: {exc}"


# Retry-history elements written by Surefire (rerunFailure/rerunError) and by
# Gradle's JUnitXmlReport mergeReruns=true (flakyFailure/flakyError). A testcase
# carrying one of these but no failure/error child eventually PASSED after
# retries — it must surface as flaky, not as a silently clean pass.
_FLAKY_XML_ELEMENTS = ("flakyFailure", "flakyError", "rerunFailure", "rerunError")


def _parse_junit_file(path: str) -> tuple[int, list[dict], list[dict]]:
    """Parse one JUnit XML file -> (passed_count, failures[], testcases[]).

    ``testcases`` carries the per-method machine record the aggregate counts
    cannot express: {"class", "name", "result": passed|failed|skipped,
    "flaky": bool}. A skipped testcase is neither passed nor failed, but its
    identity is preserved so callers can prove (not infer) execution."""
    root_el, err = _safe_parse_xml(path)
    if err:
        return 0, [{"test": path, "type": "TEST_RUNTIME_FAILED", "message": err}], []

    if root_el.tag == "testsuites":
        suites = list(root_el.findall("testsuite"))
    elif root_el.tag == "testsuite":
        suites = [root_el]
    else:
        suites = list(root_el.iter("testsuite"))

    passed = 0
    failures: list[dict] = []
    testcases: list[dict] = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}.{name}" if classname else name

            failure_el = tc.find("failure")
            error_el = tc.find("error")
            skipped_el = tc.find("skipped")
            flaky = any(tc.find(el) is not None for el in _FLAKY_XML_ELEMENTS)

            if failure_el is not None or error_el is not None:
                el = failure_el if failure_el is not None else error_el
                ftype = el.get("type", "")
                fmsg = el.get("message", "") or (el.text or "")
                failures.append({
                    "test": test_id,
                    "type": _classify_failure(ftype, fmsg),
                    "message": fmsg[:500],
                })
                result = "failed"
            elif skipped_el is not None:
                result = "skipped"
            else:
                passed += 1
                result = "passed"
            testcases.append({
                "class": classname,
                "name": name,
                "result": result,
                "flaky": flaky,
            })
    return passed, failures, testcases


def _aggregate_junit(xml_paths: list[str]) -> tuple[int, list[dict], list[dict], int, list[str]]:
    """Aggregate parsed JUnit files -> (passed, failures[], testcases[], skipped, flaky[])."""
    total_passed = 0
    all_failures: list[dict] = []
    all_testcases: list[dict] = []
    for xp in xml_paths:
        p, f, t = _parse_junit_file(xp)
        total_passed += p
        all_failures.extend(f)
        all_testcases.extend(t)
    skipped = sum(1 for t in all_testcases if t["result"] == "skipped")
    flaky = [
        f"{t['class']}.{t['name']}" if t["class"] else t["name"]
        for t in all_testcases if t["flaky"]
    ]
    return total_passed, all_failures, all_testcases, skipped, flaky


def _find_jacoco_xml_all(root: str) -> list[str]:
    """Locate every jacoco.xml that should count toward the coverage gate.

    Multi-module builds emit one report per module. Taking only the first (the old
    behaviour) measured a single module and let every other module pass the gate
    unmeasured. Rule: if a ROOT-level report exists, use only root-level reports — in a
    multi-module build that file is the aggregate report, and summing it with the
    per-module reports would double-count. Only when no root-level report exists do the
    submodule reports get aggregated.
    """
    found = _find_reports(root, _JACOCO_REL)
    if not found:
        return []
    selected = found
    # Preserve discovery order while dropping duplicates (candidates can overlap with
    # the recursive ``**/jacoco*.xml`` fallback).
    seen: set[str] = set()
    unique: list[str] = []
    for path in selected:
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _junit_paths(root: str, build_tool: str = "", task: str | None = None,
                 report_dirs: list[str] | None = None) -> list[str]:
    if report_dirs is not None:
        return sorted({str(p.resolve()) for value in report_dirs
                       for p in scoped_path(root, value).glob("TEST-*.xml")
                       if p.resolve().is_relative_to(Path(root).resolve())})
    return _task_junit_xml(root, build_tool, task) if task is not None else _find_junit_xml(root)


def _jacoco_paths(root: str, report_paths: list[str] | None = None,
                  aggregate_report: str | None = None) -> list[str]:
    if aggregate_report:
        path = scoped_path(root, aggregate_report)
        return [str(path)] if path.is_file() else []
    if report_paths is not None:
        paths = [scoped_path(root, value) for value in report_paths]
        if any(not p.is_file() for p in paths):
            return []
        return sorted(set(map(str, paths)))
    return _find_jacoco_xml_all(root)


def _coverage_result(root: str, paths: list[str], packages, excludes, aggregate_report=None) -> dict:
    parsed = _parse_jacoco_all(paths, packages, excludes)
    if parsed.get("status") != "ok":
        return parsed
    # A root location is never evidence that a report aggregates its children.
    modules = _module_dirs(root)
    expected = []
    for module in modules:
        files = [p for p in _collect_source_files(module) if "/src/main/java/" in p.replace("\\", "/")
                 and not any(Path(p).is_relative_to(Path(child)) for child in modules if child != module and Path(child).is_relative_to(Path(module)))]
        relevant = []
        for source in files:
            text = _read_text(source)
            match = re.search(r"\bpackage\s+([\w.]+)\s*;", text)
            fqcn = ((match.group(1) + ".") if match else "") + Path(source).stem
            class_name = fqcn.replace(".", "/")
            if packages and not any(fqcn == p.rstrip(".*") or fqcn.startswith(p.rstrip(".*") + ".") for p in packages):
                continue
            if excludes and any(fnmatch.fnmatchcase(class_name, p) or (p.startswith("**/") and fnmatch.fnmatchcase(class_name, p[3:])) for p in excludes):
                continue
            relevant.append(fqcn)
        if relevant:
            expected.append((module, relevant))
    measured = {c["class"] for c in parsed.get("perClass", [])}
    missing = []
    if aggregate_report:
        missing = [module for module, classes in expected if not set(classes) <= measured]
    else:
        for module, _ in expected:
            owned = [p for p in paths if max((m for m in modules if Path(p).is_relative_to(Path(m))), key=len, default=root) == module]
            if not owned:
                missing.append(module)
        seen = set()
        for path in paths:
            element, error = _safe_parse_xml(path)
            if error or element.find("group") is not None:
                parsed.update(status="partial", error="AGGREGATE_SCOPE_CONFIRMATION_REQUIRED")
            for clazz in element.iter("class") if element is not None else []:
                name = clazz.get("name")
                owner = max((m for m in modules if Path(path).is_relative_to(Path(m))), key=len, default=root)
                key = (owner, name)
                if key in seen:
                    parsed.update(status="partial", error="OVERLAPPING_COVERAGE_REPORTS")
                seen.add(key)
    parsed["missingModules"] = missing
    if missing:
        parsed.update(status="partial", error="MODULE_COVERAGE_MISSING")
    return parsed


def _find_jacoco_xml(root: str) -> str | None:
    """First JaCoCo report path (kept for callers that report a single location)."""
    found = _find_jacoco_xml_all(root)
    return found[0] if found else None


def _counter_ratio(missed: int, covered: int) -> float:
    total = missed + covered
    return (covered / total) if total > 0 else 1.0


def _parse_jacoco(jacoco_path: str, packages: list[str] | None = None,
                  excludes: list[str] | None = None) -> dict:
    """Parse a JaCoCo XML report -> per-counter coverage + per-class + uncovered[]."""
    root_el, err = _safe_parse_xml(jacoco_path)  # <report>
    if err:
        return {"status": "failed", "error": "JACOCO_PARSE_FAILED",
                "message": err, "reportPath": jacoco_path}

    def counters_of(element) -> dict:
        """Map counter type -> {missed, covered, ratio} for direct <counter> children."""
        out: dict[str, dict] = {}
        for c in element.findall("counter"):
            ctype = c.get("type", "")
            missed = int(c.get("missed", "0"))
            covered = int(c.get("covered", "0"))
            out[ctype] = {
                "missed": missed,
                "covered": covered,
                "ratio": round(_counter_ratio(missed, covered), 6),
            }
        return out

    overall = counters_of(root_el)

    per_class: list[dict] = []
    uncovered: list[dict] = []

    for package in root_el.iter("package"):
        pkg_name = package.get("name", "")
        for clazz in package.findall("class"):
            cls_name = clazz.get("name", "")
            fqcn = cls_name.replace("/", ".")
            if packages and not any(
                fqcn == pkg.rstrip(".*") or fqcn.startswith(pkg.rstrip(".*") + ".")
                for pkg in packages
            ):
                continue
            if excludes and any(fnmatch.fnmatchcase(cls_name, pat) or
                                (pat.startswith("**/") and fnmatch.fnmatchcase(cls_name, pat[3:]))
                                for pat in excludes):
                continue
            cls_counters = counters_of(clazz)
            line_ratio = cls_counters.get("LINE", {}).get("ratio", 1.0)
            branch_ratio = cls_counters.get("BRANCH", {}).get("ratio", 1.0)
            method_ratio = cls_counters.get("METHOD", {}).get("ratio", 1.0)
            per_class.append({
                "class": fqcn,
                "package": pkg_name.replace("/", "."),
                "counters": cls_counters,
            })

            # Collect uncovered methods (below full method coverage) for closer agent.
            uncovered_methods: list[dict] = []
            for method in clazz.findall("method"):
                m_counters = counters_of(method)
                m_line = m_counters.get("LINE", {})
                m_missed = m_line.get("missed", 0)
                if any(c.get("missed", 0) > 0 for c in m_counters.values()):
                    uncovered_methods.append({
                        "method": method.get("name", ""),
                        "desc": method.get("desc", ""),
                        "line": int(method.get("line", "0")),
                        "missedLines": m_missed,
                        "branchRatio": m_counters.get("BRANCH", {}).get("ratio", 1.0),
                    })

            if any(c.get("missed", 0) > 0 for c in cls_counters.values()) or uncovered_methods:
                uncovered.append({
                    "class": fqcn,
                    "lineRatio": line_ratio,
                    "branchRatio": branch_ratio,
                    "methodRatio": method_ratio,
                    "uncoveredMethods": uncovered_methods,
                })

    if packages or excludes:
        overall = _sum_counters([c["counters"] for c in per_class])
    return {
        "status": "ok",
        "coverageScope": {"packages": sorted(set(packages or [])), "excludes": sorted(set(excludes or []))},
        "reportPath": jacoco_path,
        "reportPaths": [jacoco_path],
        "overall": overall,
        "perClass": per_class,
        "uncovered": uncovered,
    }


def _sum_counters(groups: list[dict]) -> dict:
    totals = {}
    for group in groups:
        for kind, counter in group.items():
            bucket = totals.setdefault(kind, {"missed": 0, "covered": 0})
            for key in ("missed", "covered"):
                bucket[key] += counter[key]
    for bucket in totals.values():
        bucket["ratio"] = round(_counter_ratio(bucket["missed"], bucket["covered"]), 6)
    return totals


def _parse_jacoco_all(jacoco_paths: list[str], packages: list[str] | None = None,
                      excludes: list[str] | None = None) -> dict:
    """Parse and MERGE several JaCoCo reports into one coverage view.

    Counters are summed across modules (missed/covered are absolute element counts, so
    summing then re-deriving the ratio yields the true project-wide ratio — averaging
    the per-module ratios would not). ``perClass``/``uncovered`` are concatenated.
    A report that fails to parse fails the whole call: silently dropping a module would
    reproduce exactly the "unmeasured module passes the gate" bug this replaces.
    """
    if not jacoco_paths:
        return {"status": "failed", "error": "JACOCO_REPORT_NOT_FOUND",
                "message": "no JaCoCo XML report found"}
    if len(jacoco_paths) == 1:
        return _parse_jacoco(jacoco_paths[0], packages, excludes)

    totals: dict[str, dict] = {}
    per_class: list[dict] = []
    uncovered: list[dict] = []
    for path in jacoco_paths:
        parsed = _parse_jacoco(path, packages, excludes)
        if parsed.get("status") != "ok":
            return parsed
        for ctype, counter in parsed["overall"].items():
            bucket = totals.setdefault(ctype, {"missed": 0, "covered": 0})
            bucket["missed"] += counter.get("missed", 0)
            bucket["covered"] += counter.get("covered", 0)
        per_class.extend(parsed["perClass"])
        uncovered.extend(parsed["uncovered"])

    overall = {
        ctype: {
            "missed": bucket["missed"],
            "covered": bucket["covered"],
            "ratio": round(_counter_ratio(bucket["missed"], bucket["covered"]), 6),
        }
        for ctype, bucket in totals.items()
    }
    return {
        "status": "ok",
        "coverageScope": {"packages": sorted(set(packages or [])), "excludes": sorted(set(excludes or []))},
        "reportPath": jacoco_paths[0],
        "reportPaths": list(jacoco_paths),
        "overall": overall,
        "perClass": per_class,
        "uncovered": uncovered,
    }


# ---------------------------------------------------------------------------
# Spring Boot version-profile detection (Boot 2.0 – 4.x backward compatibility)
# Drives version-aware test generation. See RESEARCH_NOTES.md §8 and
# references/version-compatibility.md. Stdlib-only (regex + file walk).
# ---------------------------------------------------------------------------

_BOOT_GRADLE_RE = re.compile(
    r"org\.springframework\.boot['\"]?\s*\)?\s*version\s*[('\"]+\s*"
    r"([0-9]+\.[0-9]+\.[0-9]+[^'\")\s]*)"
)
_BOOT_GRADLE_CLASSPATH_RE = re.compile(
    r"spring-boot-gradle-plugin:([0-9]+\.[0-9]+\.[0-9]+[^'\")\s]*)"
)
_BOOT_PROP_RE = re.compile(
    r"(?:springBootVersion|spring-boot\.version|spring_boot_version)\s*[=:]\s*"
    r"['\"]?([0-9]+\.[0-9]+\.[0-9]+[^'\"\s]*)"
)
_BOOT_MAVEN_PARENT_RE = re.compile(
    r"spring-boot-starter-parent.*?<version>\s*([0-9]+\.[0-9]+\.[0-9]+[^<\s]*)\s*</version>",
    re.DOTALL,
)
_BOOT_MAVEN_DEPS_RE = re.compile(
    r"spring-boot-dependencies.*?<version>\s*([0-9]+\.[0-9]+\.[0-9]+[^<\s]*)\s*</version>",
    re.DOTALL,
)


def _read_text(path: str, limit: int = 400_000) -> str:
    """Read a text file defensively (returns '' on any error)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            value = fh.read(limit + 1)
            return value if len(value) <= limit else ""
    except (OSError, UnicodeError):
        return ""


def _strip_build_comments(text: str) -> str:
    # Preserve quoted strings (including URLs); ignore commented examples.
    pattern = r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(/\*[\s\S]*?\*/|//[^\n]*)'''
    return re.sub(pattern, lambda m: m.group(1) or " ", text)


def _pom(root: str):
    element, error = _safe_parse_xml(os.path.join(root, "pom.xml"))
    if element is not None:
        for node in element.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
    return element, error


def _pom_value(element, text: str | None) -> str | None:
    properties = {p.tag: p.text or "" for p in element.findall("./properties/*")}
    value = (text or "").strip()
    for _ in range(20):
        updated = re.sub(r"\$\{([^}]+)\}", lambda m: properties.get(m.group(1), m.group(0)), value)
        if updated == value:
            break
        value = updated
    return value if value and "${" not in value else None


def _module_dirs(root: str) -> list[str]:
    """Source-owning project directories; never discover build/cache fixture copies."""
    result = {os.path.realpath(root)}
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"build", "target", "_workspace", ".git", ".gradle",
                   ".mcp-venv", ".venv", "node_modules"} and not os.path.islink(os.path.join(base, d))]
        if any(n in names for n in ("pom.xml", "build.gradle", "build.gradle.kts")) or os.path.isdir(os.path.join(base, "src", "main")):
            result.add(os.path.realpath(base))
    return sorted(result)


def _effective_pom(root: str, java_home: str | None = None):
    with tempfile.TemporaryDirectory(prefix="harness-pom-") as directory:
        output = os.path.join(directory, "effective.xml")
        result = _run_subprocess(_platform_command([_launcher("maven", root), "-B", "-o",
                                 "help:effective-pom", "-Doutput=" + output]), root, java_home=java_home)
        element, error = _safe_parse_xml(output)
        if result["exitCode"] != 0 or result["timedOut"] or error:
            return None
        for node in element.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        return element if element.tag == "project" else element.find("project")


def _input_snapshot(root: str) -> dict:
    files = set(_collect_source_files(root))
    # Build controls can live outside the conventional gradle/ directory.
    # Include additions/deletions too; an unchanged build.gradle is insufficient.
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"build", "target", "_workspace", ".git", ".gradle",
                   ".mcp-venv", ".venv", "node_modules"} and not os.path.islink(os.path.join(base, d))]
        for name in names:
            if name.endswith((".gradle", ".gradle.kts")) or name in {"mvnw", "mvnw.cmd", "gradlew", "gradlew.bat"}:
                path = Path(base) / name
                if path.is_file() and path.resolve().is_relative_to(Path(root).resolve()):
                    files.add(str(path))
    for module in _module_dirs(root):
        files.update(os.path.join(module, name) for name in _BUILD_FILES if os.path.isfile(os.path.join(module, name)))
        for directory in ("src/main/resources", "src/test/resources", "gradle", "buildSrc", ".mvn", "docs", "specs", "requirements", "test_docs/scenarios"):
            base = scoped_path(root, os.path.join(module, directory))
            if base.is_dir():
                files.update(str(p) for p in base.rglob("*") if p.is_file() and p.resolve().is_relative_to(Path(root).resolve())
                             and not set(p.relative_to(base).parts) & {"build", "target", ".gradle", ".git", "node_modules"})
    config = Path(root) / "_workspace/00_config-harness.json"
    if config.is_file():
        files.add(str(config))
    snapshot = {}
    for raw in sorted(files):
        path = Path(raw)
        name = path.relative_to(root).as_posix()
        if "test_docs/scenarios/" in name and path.suffix == ".md":
            content = path.read_text(encoding="utf-8-sig")
            content = re.split(r"(?m)^##\s+(?:테스트 코드 매핑|검증 결과)\b", content)[0]
            digest = hashlib.sha256(content.rstrip("\r\n").encode("utf-8")).hexdigest()
        else:
            digest = file_digest(path)
        snapshot[name] = digest
    return snapshot


def _evidence_path(root: str) -> Path:
    return scoped_path(root, "_workspace/build-test-evidence.json")


def _runtime_identity(java_home: str | None = None) -> dict:
    home = java_home or os.environ.get("JAVA_HOME")
    java = str(Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")) if home else shutil.which("java")
    files = [Path(java)] if java else []
    if home:
        files.append(Path(home) / "release")
    return {"javaHome": os.path.realpath(home) if home else None,
            "java": os.path.realpath(java) if java else None,
            "files": {str(p.resolve()): file_digest(p) if p.is_file() else None for p in files},
            "options": {key: os.environ.get(key) for key in
                        ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "JAVA_OPTS", "GRADLE_OPTS", "MAVEN_OPTS",
                         "MAVEN_ARGS", "GRADLE_USER_HOME")}}


def _fresh_run(root: str, reports: list[str], inputs: dict | None = None, coverage: bool = False,
               java_home: str | None = None, run_context: dict | None = None) -> tuple[bool, str]:
    try:
        evidence = json.loads(_evidence_path(root).read_text(encoding="utf-8"))
        if evidence.get("exitCode") != 0 or evidence.get("timedOut") is not False:
            return False, "RUN_NOT_SUCCESSFUL"
        current = inputs if inputs is not None else _input_snapshot(root)
        if evidence.get("inputsStable") is not True or evidence.get("root") != os.path.realpath(root) or evidence.get("inputs") != current:
            return False, "RUN_INPUTS_CHANGED"
        context = evidence.get("runContext")
        if not isinstance(context, dict):
            return False, "RUN_CONTEXT_REQUIRED"
        if run_context is not None and context != run_context:
            return False, "RUN_SCOPE_CHANGED"
        if java_home is None:
            config = Path(root) / "_workspace/00_config-harness.json"
            if config.is_file():
                java_home = json.loads(config.read_text(encoding="utf-8")).get("javaHome")
        if context.get("runtime") != _runtime_identity(java_home):
            return False, "RUN_JDK_CHANGED"
        saved = evidence.get("reports", {})
        if not saved or any(not Path(p).is_file() or digest != file_digest(Path(p)) for p, digest in saved.items()):
            return False, "REPORT_EVIDENCE_MISSING_OR_CHANGED"
        if coverage and evidence.get("coverageDataFresh") is not True:
            return False, "COVERAGE_DATA_EVIDENCE_REQUIRED"
        if coverage:
            junit = evidence.get("reportPaths", [])
            if not junit:
                return False, "JUNIT_EVIDENCE_REQUIRED"
            passed, failures, *_ = _aggregate_junit(junit)
            if passed <= 0 or failures:
                return False, "RUN_NOT_SUCCESSFUL"
        if not reports or any(saved.get(os.path.realpath(p)) != file_digest(Path(p)) for p in reports):
            return False, "REPORT_EVIDENCE_MISSING_OR_CHANGED"
        return True, ""
    except (OSError, ValueError, TypeError):
        return False, "RUN_EVIDENCE_REQUIRED"


def _reusable_run(root: str, context: dict, inputs: dict, java_home: str | None) -> dict | None:
    try:
        evidence = json.loads(_evidence_path(root).read_text(encoding="utf-8"))
        junit = evidence.get("reportPaths", [])
        coverage = evidence.get("coverageReportPaths", [])
        if context["withCoverage"] and not coverage:
            return None
        fresh, _ = _fresh_run(root, junit + coverage, inputs, context["withCoverage"], java_home, context)
        if not fresh:
            return None
        passed, failures, cases, skipped, flaky = _aggregate_junit(junit)
        if passed <= 0 or failures:
            return None
        return {"status": "ok", "buildTool": context["buildTool"], "task": context["task"],
                "command": evidence.get("command"), "testPatterns": context["testPatterns"],
                "testPattern": ",".join(context["testPatterns"]), "withCoverage": context["withCoverage"],
                "networkOffline": evidence.get("networkOffline"), "exitCode": 0, "timedOut": False,
                "passed": passed, "failed": [], "failureClasses": [], "skipped": skipped,
                "testcases": cases, "flaky": flaky, "reportPaths": junit, "coverageReportPaths": coverage,
                "inputsStable": True, "coverageDataFresh": evidence.get("coverageDataFresh"),
                "executionEvidence": {"path": str(_evidence_path(root)), "id": evidence["executionId"]},
                "reused": True, "reuseReason": "MATCHING_INPUTS_SCOPE_JDK_REPORTS", "nextActions": [],
                "stdoutTail": "", "stderrTail": ""}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _detect_boot_version(root: str) -> tuple[str | None, str]:
    """Best-effort Spring Boot version from build files. Returns (version|None, source)."""
    for name in ("build.gradle.kts", "build.gradle"):
        text = _read_text(os.path.join(root, name))
        if text:
            text = _strip_build_comments(text)
            m = _BOOT_GRADLE_RE.search(text) or _BOOT_GRADLE_CLASSPATH_RE.search(text)
            if m:
                return m.group(1), name
    props = _read_text(os.path.join(root, "gradle.properties"))
    if props:
        m = _BOOT_PROP_RE.search(props)
        if m:
            return m.group(1), "gradle.properties"
    element, _ = _pom(root)
    if element is not None:
        candidates = [element.find("parent"), *element.findall("./dependencyManagement/dependencies/dependency")]
        for node in candidates:
            if node is not None and node.findtext("groupId") == "org.springframework.boot" and node.findtext("artifactId") in {"spring-boot-starter-parent", "spring-boot-dependencies"}:
                value = _pom_value(element, node.findtext("version"))
                if value:
                    return value, "pom.xml"
    return None, ""


def _scan_imports(root: str, subdir: str, needles: tuple[str, ...],
                  max_files: int = 400) -> dict:
    """Count Java files under root/subdir containing each needle substring."""
    counts = {n: 0 for n in needles}
    counts["_incomplete"] = False
    for path in _collect_source_files(root):
        if "/" + subdir + "/" not in path.replace("\\", "/"):
            continue
        text = _read_text(path, limit=10_000_000)
        if not text and os.path.getsize(path):
            counts["_incomplete"] = True
        for n in needles:
            if n in text:
                counts[n] += 1
    return counts


def _gradle_context(root: str, java_home: str | None = None) -> dict | None:
    script = """gradle.projectsEvaluated {
      def modules = gradle.rootProject.allprojects.collect { p ->
        def boot = p.plugins.findPlugin('org.springframework.boot')
        def source = p.extensions.findByName('sourceSets')
        def tasks = p.tasks.withType(org.gradle.api.tasks.testing.Test).collect { t ->
          [task:t.path, reportDir:t.reports.junitXml.destination.absolutePath,
           executionData:t.extensions.findByName('jacoco')?.destinationFile?.absolutePath]
        }
        def reports = p.tasks.withType(org.gradle.testing.jacoco.tasks.JacocoReport).collect { t ->
          [task:t.path, xmlEnabled:t.reports.xml.enabled, reportPath:t.reports.xml.destination.absolutePath]
        }
        [projectDir:p.projectDir.absolutePath, bootJar:boot ? boot.class.protectionDomain.codeSource.location.toString() : null,
         sourceRoots:source ? source.collectMany { it.allJava.srcDirs.collect { it.absolutePath } } : [],
         testTasks:tasks, coverageReports:reports]
      }
      println('HARNESS_CONTEXT:' + groovy.json.JsonOutput.toJson(modules))
    }"""
    # Use property APIs according to the running wrapper; Gradle 8+ removed enabled/destination.
    script = script.replace("t.reports.junitXml.destination.absolutePath", "(t.reports.junitXml.hasProperty('outputLocation') ? t.reports.junitXml.outputLocation.get().asFile : t.reports.junitXml.destination).absolutePath")
    script = script.replace("t.reports.xml.enabled", "(t.reports.xml.hasProperty('required') ? t.reports.xml.required.get() : t.reports.xml.enabled)")
    script = script.replace("t.reports.xml.destination.absolutePath", "(t.reports.xml.hasProperty('outputLocation') ? t.reports.xml.outputLocation.get().asFile : t.reports.xml.destination).absolutePath")
    with tempfile.TemporaryDirectory(prefix="harness-context-") as directory:
        path = Path(directory) / "context.gradle"
        path.write_text(script, encoding="utf-8")
        result = _run_subprocess(_platform_command([_launcher("gradle", root), "help", "--offline", "--console=plain", "-q", "--init-script", str(path)]), root, java_home=java_home)
    if result["exitCode"] != 0 or result["timedOut"]:
        return None
    match = re.search(r"(?m)^HARNESS_CONTEXT:(.+)$", result.get("stdout", ""))
    try:
        return {"modules": json.loads(match.group(1))} if match else None
    except ValueError:
        return None


def _profile_from_version(bv: str | None) -> dict:
    """Derive idioms from a confirmed Boot version; unknown versions stay unset."""
    major = minor = 0
    if bv:
        parts = bv.split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            major = minor = 0
    if major not in (2, 3, 4):
        return dict.fromkeys(("bootMajor", "bootMinor", "namespace", "junitEngine", "mockAnnotation",
                              "mockImport", "javaBaseline", "gradleTestMode"))
    namespace = "javax" if major == 2 else "jakarta"
    if major >= 4 or (major == 3 and minor >= 4):
        mock, mock_import = ("MockitoBean",
                             "org.springframework.test.context.bean.override.mockito.MockitoBean")
    else:
        mock, mock_import = ("MockBean",
                             "org.springframework.boot.test.mock.mockito.MockBean")
    junit_engine = "junit4" if (major == 2 and minor < 2) else "jupiter"
    return {
        "bootMajor": major,
        "bootMinor": minor,
        "namespace": namespace,
        "junitEngine": junit_engine,
        "mockAnnotation": mock,
        "mockImport": mock_import,
        "javaBaseline": 8 if major == 2 else 17,
        "gradleTestMode": "useJUnit" if junit_engine == "junit4" else "useJUnitPlatform",
        "webMvcTestImport": "org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest" if major >= 4 else "org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest",
        "dataJpaTestImport": "org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest" if major >= 4 else "org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest",
        "sliceTestStarters": ["spring-boot-starter-webmvc-test", "spring-boot-starter-data-jpa-test"] if major >= 4 else ["spring-boot-starter-test"],
    }


def _profile_conflict(field: str, build_value: str, source_value: str, evidence: str,
                      source_label: str, conflicts: list, notes: list) -> None:
    """Record a build-file-vs-source profile conflict (never auto-applied) into
    conflicts[]/notes[] when the source-derived value disagrees with the build file."""
    if source_value == build_value:
        return
    conflicts.append({
        "field": field,
        "buildFileValue": build_value,
        "sourceValue": source_value,
        "evidence": evidence,
    })
    notes.append(f"{field} conflict (NOT auto-applied): build-file={build_value} "
                 f"vs {source_label}={source_value}; confirm before use")


def _decode_output(value) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            # Java/cmd may emit the Windows ANSI encoding even with PYTHONUTF8=1.
            value = value.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")
    return value or ""


def _output_tail(value) -> str:
    return _decode_output(value)[-4000:]


def _run_subprocess(cmd: "list[str] | str", cwd: str, java_home: str | None = None) -> dict:
    """Run a subprocess and return execution metadata.

    POSIX는 argv 리스트, Windows 배치 래퍼는 사전 조립된 `cmd.exe /s /c "…"` 문자열을
    받는다(Windows에서 문자열은 CreateProcess 커맨드라인으로 그대로 전달됨 — 재인용 없음).
    Offline mode is enforced by the build CLI flags (gradle --offline / maven -o)
    added in run_targeted_tests, not here; this only inherits the current environment.
    """
    env = dict(os.environ)
    if java_home:
        home = Path(java_home).resolve()
        if not (home / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file():
            raise ValueError("INVALID_JAVA_HOME: " + str(home))
        env["JAVA_HOME"] = str(home)
        env["PATH"] = str(home / "bin") + os.pathsep + env.get("PATH", "")
    try:
        import time
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=os.name != "nt")
        try:
            deadline = time.monotonic() + _RUN_TIMEOUT
            while True:
                try:
                    from anyio.from_thread import check_cancelled
                    check_cancelled()
                except RuntimeError:
                    pass
                remaining = deadline - time.monotonic()
                try:
                    stdout, stderr = proc.communicate(timeout=max(.01, min(1, remaining)))
                    break
                except subprocess.TimeoutExpired:
                    if remaining <= 1:
                        raise
        except BaseException:
            stop_process_tree(proc)
            proc.communicate()
            raise
        return {
            "exitCode": proc.returncode,
            "stdoutTail": _output_tail(stdout),
            "stderrTail": _output_tail(stderr),
            "stdout": _decode_output(stdout),
            "timedOut": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exitCode": -1,
            "stdoutTail": _output_tail(exc.stdout),
            "stderrTail": _output_tail(exc.stderr),
            "timedOut": True,
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "exitCode": -1,
            "stdoutTail": "",
            "stderrTail": f"failed to launch build command: {exc}",
            "timedOut": False,
        }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _project_root(root: str) -> str:
    """Keep legacy cwd defaults; portable MCP must name its target explicitly."""
    if os.environ.get("HARNESS_HOST") == "codex":
        if not root.strip() or not Path(root).is_absolute():
            raise ToolError("PROJECT_ROOT_REQUIRED: pass the confirmed absolute project root")
        if not os.path.isdir(root):
            raise ToolError("INVALID_PROJECT_ROOT: root directory does not exist")
    return os.path.abspath(root)


@mcp.tool()
def health(root: str | None = None) -> dict:
    """Side-effect-free diagnostic probe: report server config status.

    Reports the plugin version and whether outbound network is allowed
    (BUILD_TEST_ALLOW_NETWORK), without running any build. Never raises.
    """
    try:
        network_allowed = _network_allowed()
    except Exception:
        network_allowed = False
    scope, scope_error = None, None
    if root is not None:
        try:
            scope = _project_root(root)
        except (ToolError, ValueError, OSError) as exc:
            scope_error = str(exc)
    return {
        "server": "build-test",
        "pluginVersion": _plugin_version(),
        "networkAllowed": network_allowed,
        "projectRoot": scope,
        "rootRequired": os.environ.get("HARNESS_HOST") == "codex",
        "scopeError": scope_error,
        "runtime": runtime_info(),
    }


@mcp.tool()
def detect_build_tool(root: str = ".") -> dict:
    """Detect whether the project root uses Gradle or Maven (wrapper aware).

    Returns {status, buildTool, wrapper} or a BUILD_TOOL_UNDETECTED failure.
    """
    return _detect(_project_root(root))


@mcp.tool()
def detect_spring_profile(root: str = ".", java_home: str | None = None) -> dict:
    """Detect the target's Spring Boot version profile for version-aware test generation.

    Reads build.gradle[.kts]/pom.xml/gradle.properties for the Boot version, scans
    src/main for javax vs jakarta imports and src/test for the JUnit engine, then derives
    namespace, junitEngine, mockAnnotation/mockImport, javaBaseline and gradleTestMode.
    Supports Boot 2.0–4.x. Returns springProfile.degraded=true when the version cannot be
    detected (caller must confirm the actual version before generating tests).
    """
    root = _project_root(root)
    if not os.path.isdir(root):
        return {"status": "failed", "error": "PROJECT_ROOT_NOT_FOUND",
                "message": f"directory not found: {root}"}

    bv, bv_source = _detect_boot_version(root)
    detected = _detect(root)
    if detected.get("buildTool") == "maven" and bv is None:
        effective = _effective_pom(root, java_home)
        if effective is not None:
            for dependency in [effective.find("parent"), *effective.findall("./dependencyManagement/dependencies/dependency")]:
                if dependency is not None and dependency.findtext("groupId") == "org.springframework.boot" and dependency.findtext("artifactId") in {"spring-boot-starter-parent", "spring-boot-dependencies", "spring-boot"}:
                    bv = _pom_value(effective, dependency.findtext("version"))
                    if bv:
                        bv_source = "effective-pom (offline)"
                        break
    elif detected.get("buildTool") == "gradle":
        context = _gradle_context(root, java_home)
        if context:
            versions = {m.group(1) for item in context["modules"] if (m := re.search(r"spring-boot-gradle-plugin-([\d][\w.+-]*)\.jar", item.get("bootJar") or ""))}
            if len(versions) == 1:
                bv, bv_source = versions.pop(), "configured Gradle plugin (offline)"
            elif len(versions) > 1:
                bv, bv_source = None, "multiple module versions; narrow root"
    prof = _profile_from_version(bv)
    notes: list[str] = []
    next_actions: list[str] = []
    conflicts: list[dict] = []

    # Namespace conflict from actual main-source imports (mixed-project defense).
    # Per fallback-policy.md #6 we DO NOT silently override: the build-file-derived
    # value stays as the proposed default and the conflict is surfaced for the
    # caller (agent) to confirm via AskUserQuestion.
    main_ns = _scan_imports(root, "src/main/java", (
        "import javax.persistence", "import jakarta.persistence",
        "import javax.validation", "import jakarta.validation",
        "import javax.servlet", "import jakarta.servlet",
    ))
    javax_hits = (main_ns["import javax.persistence"] + main_ns["import javax.validation"]
                  + main_ns["import javax.servlet"])
    jakarta_hits = (main_ns["import jakarta.persistence"] + main_ns["import jakarta.validation"]
                    + main_ns["import jakarta.servlet"])
    if javax_hits or jakarta_hits:
        src_ns = "javax" if javax_hits >= jakarta_hits else "jakarta"
        _profile_conflict("namespace", prof["namespace"], src_ns,
                          f"javax={javax_hits}, jakarta={jakarta_hits} (src/main imports)",
                          "source", conflicts, notes)

    # JUnit engine conflict from existing tests; note vintage availability.
    test_eng = _scan_imports(root, "src/test/java",
                             ("import org.junit.jupiter", "import org.junit.Test", "@RunWith"))
    build_text = (_read_text(os.path.join(root, "build.gradle.kts"))
                  + _read_text(os.path.join(root, "build.gradle"))
                  + _read_text(os.path.join(root, "pom.xml")))
    jupiter_tests = test_eng["import org.junit.jupiter"]
    junit4_tests = test_eng["import org.junit.Test"]
    if jupiter_tests or junit4_tests:
        src_engine = "jupiter" if jupiter_tests >= junit4_tests else "junit4"
        _profile_conflict("junitEngine", prof["junitEngine"], src_engine,
                          f"jupiter={jupiter_tests}, junit4={junit4_tests} (src/test imports)",
                          "tests", conflicts, notes)
    if "junit-vintage" in build_text:
        notes.append("junit-vintage-engine present: JUnit4 tests run alongside Jupiter")

    requires_confirmation = bool(conflicts) or main_ns.get("_incomplete", False) or test_eng.get("_incomplete", False)
    if requires_confirmation:
        next_actions.append("PROFILE_CONFLICT: build-file vs source disagree; the main conversation must "
                            "confirm the correct value via AskUserQuestion (interactive) or stop (CI). "
                            "See references/fallback-policy.md #6.")

    degraded = prof["bootMajor"] is None or main_ns.get("_incomplete", False) or test_eng.get("_incomplete", False)
    if degraded:
        notes.append("Spring Boot profile is unknown, unsupported, or has incomplete source evidence.")
        next_actions.append("INTERVIEW_REQUIRED: Spring Boot version undetected. The main conversation must ask "
                            "the user for the exact Boot version (major and minor) via AskUserQuestion (interactive) or "
                            "stop (CI). Do NOT assume a profile. See references/fallback-policy.md #4.")

    return {
        "status": "partial" if degraded else "ok",
        "springProfile": {
            "bootVersion": bv,
            "bootMajor": prof["bootMajor"],
            "namespace": prof["namespace"],
            "junitEngine": prof["junitEngine"],
            "mockAnnotation": prof["mockAnnotation"],
            "mockImport": prof["mockImport"],
            "javaBaseline": prof["javaBaseline"],
            "gradleTestMode": prof["gradleTestMode"],
            "webMvcTestImport": prof.get("webMvcTestImport"),
            "dataJpaTestImport": prof.get("dataJpaTestImport"),
            "sliceTestStarters": prof.get("sliceTestStarters", []),
            "degraded": degraded,
        },
        "versionSource": bv_source,
        "interviewRequired": degraded,
        "requiresConfirmation": requires_confirmation,
        "conflicts": conflicts,
        "notes": notes,
        "nextActions": next_actions,
    }


@mcp.tool()
def list_test_tasks(root: str = ".", java_home: str | None = None) -> dict:
    """Discover configured Gradle Test tasks; Maven reports only local lifecycle evidence.

    Inherited/profile Maven configuration is not guessed from a static POM.
    Gradle discovery runs the build's configuration phase offline, without running tests.
    """
    root = _project_root(root)
    det = _detect(root)
    if det.get("status") != "ok":
        return det
    if det["buildTool"] == "gradle":
        context = _gradle_context(root, java_home)
        if context:
            tasks = [dict(t, desc="Configured Gradle Test task", projectDir=p["projectDir"])
                     for p in context["modules"] for t in p["testTasks"]]
            return {"status": "ok", "buildTool": "gradle", "wrapper": det["wrapper"], "tasks": tasks,
                    "modules": context["modules"], "configurationVerified": True, "note": ""}
        script = """allprojects { p ->
    afterEvaluate {
        tasks.withType(org.gradle.api.tasks.testing.Test).each { t ->
            println('HARNESS_TEST_TASK:' + t.path)
        }
    }
}
"""
        with tempfile.TemporaryDirectory(prefix="harness-tasks-") as temp:
            init = os.path.join(temp, "tasks.gradle")
            with open(init, "w", encoding="utf-8") as fh:
                fh.write(script)
            cmd = _platform_command([_launcher("gradle", root), "help", "--offline",
                                     "--console=plain", "-q", "--init-script", init])
            result = _run_subprocess(cmd, root, java_home=java_home)
        if result["exitCode"] != 0 or result["timedOut"]:
            return {"status": "failed", "error": "TASK_DISCOVERY_FAILED", **{k:v for k,v in result.items() if k != "stdout"}, "tasks": []}
        tasks = [{"task": value, "desc": "Configured Gradle Test task"}
                 for value in sorted(set(re.findall(r"(?m)^HARNESS_TEST_TASK:(\S+)\s*$",
                                                     result.get("stdout", result["stdoutTail"]))))]
        verified = bool(tasks)
        if not verified:
            return {"status": "partial", "error": "TASK_DISCOVERY_INCOMPLETE", "tasks": [], "configurationVerified": False}
    else:
        tasks = [{"task": "test", "desc": "Maven test lifecycle (Surefire)"}]
        el, error = _safe_parse_xml(os.path.join(root, "pom.xml"))
        if error:
            return {"status": "failed", "error": "TASK_DISCOVERY_FAILED", "message": error, "tasks": []}
        effective = _effective_pom(root, java_home)
        if effective is not None:
            el = effective
        # Inspect active build/plugins, never pluginManagement.
        for node in el.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        for plugin in el.findall("./build/plugins/plugin"):
            if plugin.findtext("artifactId") == "maven-failsafe-plugin":
                goals = {g.text for g in plugin.findall("./executions/execution/goals/goal")}
                if {"integration-test", "verify"} <= goals:
                    tasks.append({"task": "verify", "desc": "Locally bound Failsafe integration tests"})
        verified = effective is not None
    return {"status": "ok", "buildTool": det["buildTool"], "wrapper": det["wrapper"],
            "tasks": tasks, "configurationVerified": verified,
            "note": "" if verified else "Local POM only; inherited and active-profile bindings need effective-POM verification."}


def _launcher(build_tool: str, root: str) -> str:
    if build_tool == "gradle":
        names = ("gradlew.bat", "gradlew.cmd") if os.name == "nt" else ("gradlew",)
        fallback = "gradle"
    else:
        names = ("mvnw.cmd", "mvnw.bat") if os.name == "nt" else ("mvnw",)
        fallback = "mvn"
    # An unqualified batch name can give Gradle's %~dp0 the caller's cwd.
    # Resolve PATH launchers before cmd.exe invocation, just like project wrappers.
    if os.name == "nt":
        fallback = shutil.which(fallback) or fallback
    return next((os.path.join(root, n) for n in names if os.path.isfile(os.path.join(root, n))), fallback)


def _platform_command(argv: list[str]) -> list[str] | str:
    if os.name == "nt":
        # /d disables AutoRun and /v:off prevents ! expansion. Refuse cmd expansion
        # metacharacters even in paths instead of silently executing a different command.
        if any(re.search(r'["%\r\n&|<>^]', arg) for arg in argv):
            raise ValueError("Unsupported cmd.exe metacharacter in build argument/path")
        return 'cmd.exe /d /v:off /s /c "' + ' '.join('"' + arg + '"' for arg in argv) + '"'
    return argv


def _build_test_command(build_tool: str, root: str, test_pattern: str,
                        with_coverage: bool, offline: bool, task: str = "test",
                        test_patterns: list[str] | None = None,
                        coverage_task: str | None = None) -> list[str] | str:
    patterns = test_patterns if test_patterns is not None else test_pattern.split(",")
    launcher = _launcher(build_tool, root)
    if build_tool == "gradle":
        cmd = [launcher, task]
        for pattern in patterns:
            cmd.extend(["--tests", pattern.replace("#", ".")])
        if with_coverage:
            # Custom Test tasks need an explicitly configured JaCoCo report task.
            leaf = task.rsplit(":", 1)[-1]
            prefix = task[:-len(leaf)]
            if coverage_task:
                cmd.append(coverage_task)
            elif leaf == "test":
                cmd.append(prefix + "jacocoTestReport")
            else:
                raise ValueError("Custom Gradle Test task requires an explicitly configured coverage_task")
        if offline:
            cmd.append("--offline")
    else:
        selector = "it.test" if task == "verify" else "test"
        cmd = [launcher, "-B", task, f"-D{selector}=" + ",".join(patterns)]
        if with_coverage:
            cmd.append("jacoco:report")
        if offline:
            cmd.append("-o")
    return _platform_command(cmd)


# Locks are per canonical project: threads serialize before taking the OS lock;
# separate Claude sessions also share the OS lock. No lock files in the user's repo.
_BUILD_LOCKS = [threading.Lock() for _ in range(64)]


@contextmanager
def _thread_build_lock(lock):
    if not lock.acquire(timeout=_RUN_TIMEOUT):
        raise TimeoutError("Project build thread lock timed out")
    try:
        yield
    finally:
        lock.release()


@contextmanager
def _project_build_lock(root: str):
    key = hashlib.sha256(os.path.normcase(os.path.realpath(root)).encode()).hexdigest()
    with _thread_build_lock(_BUILD_LOCKS[int(key[:8], 16) % len(_BUILD_LOCKS)]):
        with open(os.path.join(tempfile.gettempdir(), "harness-build-" + key + ".lock"), "a+b") as fh:
            if os.name == "nt":
                import msvcrt
                if fh.tell() == 0:
                    fh.write(b"0"); fh.flush()
                fh.seek(0)
                # Retry bounded by the build timeout rather than msvcrt's 10s default.
                import time
                deadline = time.monotonic() + _RUN_TIMEOUT
                while True:
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Project build lock timed out")
                        time.sleep(.1)
            else:
                import fcntl
                import time
                deadline = time.monotonic() + _RUN_TIMEOUT
                while True:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Project build lock timed out")
                        time.sleep(.1)
            try:
                yield
            finally:
                if os.name == "nt":
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh, fcntl.LOCK_UN)


def _task_junit_xml(root: str, build_tool: str, task: str) -> list[str]:
    if build_tool == "gradle":
        parts = task.strip(":").split(":")
        base = os.path.join(root, *parts[:-1]) if len(parts) > 1 else root
        paths = glob.glob(os.path.join(base, "**", "build", "test-results", parts[-1], "TEST-*.xml"), recursive=True)
    else:
        folder = "failsafe-reports" if task == "verify" else "surefire-reports"
        paths = glob.glob(os.path.join(root, "**", "target", folder, "TEST-*.xml"), recursive=True)
    return sorted(set(os.path.abspath(p) for p in paths))


def _gradle_task_matches(path: str, selector: str) -> bool:
    # An unqualified selector runs matching tasks in the root and subprojects.
    return (path.rsplit(":", 1)[-1] == selector if ":" not in selector
            else path == ":" + selector.lstrip(":"))


def _coverage_data_paths(root: str, build_tool: str, task: str, context: dict | None) -> tuple[list[str], bool]:
    if build_tool == "gradle":
        if not context:
            return [], False
        tasks = [t for m in context["modules"] for t in m["testTasks"] if _gradle_task_matches(t["task"], task)]
        paths = [str(scoped_path(root, t["executionData"])) for t in tasks if t.get("executionData")]
        return paths, bool(paths) and len(paths) == len(tasks)
    paths = []
    for module in _module_dirs(root):
        element, _ = _pom(module)
        if element is None:
            return [], False
        plugin = next((p for p in element.findall("./build/plugins/plugin") if p.findtext("artifactId") == "jacoco-maven-plugin"), None)
        if plugin is None:
            return [], False  # inherited/profile destination needs confirmed effective config
        build_directory = element.findtext("./build/directory", "target").replace("${project.basedir}", module)
        build_directory = _pom_value(element, build_directory)
        if not build_directory:
            return [], False
        destinations = [plugin.findtext("./configuration/destFile", str(Path(build_directory) / "jacoco.exec"))]
        if any(g.text == "prepare-agent-integration" for g in plugin.findall("./executions/execution/goals/goal")):
            destinations.append(str(Path(build_directory) / "jacoco-it.exec"))
        destinations.extend(e.findtext("./configuration/destFile") for e in plugin.findall("./executions/execution") if e.findtext("./configuration/destFile"))
        for raw in destinations:
            raw = raw.replace("${project.build.directory}", str(Path(module) / build_directory)).replace("${project.basedir}", module)
            value = _pom_value(element, raw)
            if not value:
                return [], False
            if "${" in value:
                return [], False
            paths.append(str(scoped_path(root, str(Path(module) / value))))
    return paths, bool(paths)


def _classify_run_status(timed_out: bool, xml_paths: list, exit_code: int,
                         failures: list, passed: int | None = None) -> str:
    """Map a test run outcome to ok/partial/failed.

    A non-zero build is never "ok" even when the parsed reports show no individual
    test failure (compile error, coverage-verification failure, etc.).
    """
    if timed_out:
        return "failed"
    if not xml_paths:
        return "failed"
    if failures:
        return "partial"
    if exit_code != 0 or passed == 0:
        return "failed"
    return "ok"


@mcp.tool()
def run_targeted_tests(build_tool: str, test_pattern: str = "", root: str = ".",
                       with_coverage: bool = True, online: bool = False, task: str = "test",
                       test_patterns: list[str] | None = None, coverage_task: str | None = None,
                       report_dirs: list[str] | None = None, report_paths: list[str] | None = None,
                       java_home: str | None = None, reuse_if_fresh: bool = False) -> dict:
    """Run the NARROWEST test scope for a given pattern; return a TestRunResult.

    Gradle : ./gradlew test --tests <pat> [jacocoTestReport] [--offline]
    Maven  : mvn -B test -Dtest=<pat> [jacoco:report] [-o]

    All arguments are shlex-quoted. Network is OFF by default unless
    BUILD_TEST_ALLOW_NETWORK is set.

    `online=True` requests a one-time NETWORK-ON run so a COLD dependency cache (or
    newly added JaCoCo plugins) can be resolved — Gradle `--offline` fails fast
    when a required module is not cached (Gradle Dependency Caching). The caller (skill)
    decides this after `check_dependency_cache` + user approval (fallback-policy.md #18);
    once primed, subsequent runs go offline again.
    """
    root = _project_root(root)
    build_tool = (build_tool or "").strip().lower()
    if build_tool not in ("gradle", "maven"):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"unsupported build_tool: {build_tool!r}"}

    if not os.path.isdir(root):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"directory not found: {root}"}

    if (test_pattern and test_patterns is not None) or not (test_pattern or test_patterns):
        return {"status": "failed", "error": "INVALID_TEST_PATTERN",
                "message": "Provide exactly one nonempty test_pattern or test_patterns input."}
    patterns = test_patterns if test_patterns is not None else test_pattern.split(",")
    if not all(isinstance(p, str) and re.fullmatch(r"[\w.$#*,!\[\]]+", p) for p in patterns):
        return {"status": "failed", "error": "INVALID_TEST_PATTERN",
                "message": "Only identifier characters and supported test selectors are accepted."}
    if build_tool == "gradle" and any(re.search(r"[!\[\]]", p) for p in patterns):
        return {"status": "failed", "error": "INVALID_TEST_PATTERN",
                "message": "Gradle --tests does not support Maven exclusion/parameter selectors."}
    if not re.fullmatch(r":?[\w-]+(?::[\w-]+)*", task) or (build_tool == "maven" and task not in ("test", "verify")):
        return {"status": "failed", "error": "INVALID_TEST_TASK", "message": "Unsupported test task."}
    offline = (not _network_allowed()) and (not online)
    pattern_q = shlex.quote(",".join(patterns))
    try:
        if coverage_task and (build_tool != "gradle" or not re.fullmatch(r":?[\w-]+(?::[\w-]+)*", coverage_task)):
            raise ValueError("coverage_task must be a configured Gradle task path")
        cmd = _build_test_command(build_tool, root, "", with_coverage, offline, task, patterns, coverage_task)
    except ValueError as exc:
        return {"status": "failed", "error": "INVALID_BUILD_ARGUMENT", "message": str(exc)}

    # Human-readable command string with shlex quoting for transparency/logging.
    # (Windows 배치 경로는 이미 cmd.exe /s /c 문자열로 조립됨 — 그대로 기록)
    display_cmd = cmd if isinstance(cmd, str) else " ".join(shlex.quote(part) for part in cmd)

    try:
        with _project_build_lock(root):
            before = _input_snapshot(root)
            run_context = {"buildTool": build_tool, "task": task, "testPatterns": sorted(set(patterns)),
                           "withCoverage": with_coverage, "coverageTask": coverage_task,
                           "reportDirs": sorted(report_dirs) if report_dirs is not None else None,
                           "reportPaths": sorted(report_paths) if report_paths is not None else None,
                           "runtime": _runtime_identity(java_home)}
            if reuse_if_fresh:
                cached = _reusable_run(root, run_context, before, java_home)
                if cached is not None:
                    return cached
            execution_id = uuid.uuid4().hex
            atomic_json(_evidence_path(root), {"root": os.path.realpath(root), "inputs": before,
                        "inputsStable": False, "exitCode": None, "timedOut": False, "reports": {}})
            selected_coverage = _jacoco_paths(root, report_paths) if with_coverage else []
            context = _gradle_context(root, java_home) if build_tool == "gradle" else None
            if build_tool == "gradle" and report_paths is None:
                leaf = task.rsplit(":", 1)[-1]
                coverage_name = coverage_task or (task[:-len(leaf)] + "jacocoTestReport")
                known = [r["reportPath"] for m in (context or {}).get("modules", []) for r in m["coverageReports"] if _gradle_task_matches(r["task"], coverage_name)]
                selected_coverage = [str(scoped_path(root, p)) for p in known if os.path.isfile(p)] if context else [p for p in selected_coverage if Path(p).name == coverage_name.rsplit(":", 1)[-1] + ".xml"]
                if report_dirs is None and context:
                    report_dirs = [t["reportDir"] for m in context["modules"] for t in m["testTasks"] if _gradle_task_matches(t["task"], task)]
            # Discover configured report directories before invalidating prior results.
            for stale in _junit_paths(root, build_tool, task, report_dirs):
                os.remove(stale)
            for stale in selected_coverage:
                # No old coverage XML may masquerade as evidence of this run.
                os.remove(stale)
            data_paths, data_confirmed = _coverage_data_paths(root, build_tool, task, context) if with_coverage else ([], True)
            for path in data_paths:
                if os.path.isfile(path):
                    os.remove(path)
            exec_meta = _run_subprocess(cmd, cwd=root, java_home=java_home)
            xml_paths = _junit_paths(root, build_tool, task, report_dirs)
            total_passed, all_failures, all_testcases, skipped, flaky = _aggregate_junit(xml_paths)
            after = _input_snapshot(root)
            measured = _jacoco_paths(root, report_paths) if with_coverage else []
            if build_tool == "gradle" and report_paths is None:
                measured = [p for p in measured if p in selected_coverage or (context and p in known) or (not context and Path(p).name == coverage_name.rsplit(":", 1)[-1] + ".xml")]
            reports = xml_paths + measured
            evidence = {"root": os.path.realpath(root), "inputs": before, "inputsStable": before == after,
                        "task": task, "testPatterns": patterns, "javaHome": java_home or os.environ.get("JAVA_HOME"),
                        "coverageDataFresh": data_confirmed,
                        "exitCode": exec_meta["exitCode"], "timedOut": exec_meta["timedOut"],
                        "reports": {os.path.realpath(p): file_digest(Path(p)) for p in reports},
                        "runContext": run_context, "executionId": execution_id, "command": display_cmd,
                        "networkOffline": offline,
                        "reportPaths": [os.path.abspath(p) for p in xml_paths],
                        "coverageReportPaths": [os.path.abspath(p) for p in measured]}
            atomic_json(_evidence_path(root), evidence)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "error": "REPORT_PREPARATION_FAILED", "message": str(exc)}
    status = _classify_run_status(exec_meta["timedOut"], xml_paths,
                                  exec_meta["exitCode"], all_failures, total_passed)
    if before != after:
        status = "failed"
    elif with_coverage and not data_confirmed and status == "ok":
        status = "partial"
    failure_classes = sorted({f["type"] for f in all_failures})
    if status == "failed" and not failure_classes:
        failure_classes = [_classify_failure("", exec_meta["stderrTail"] + exec_meta["stdoutTail"])]

    return {
        "status": status,
        "buildTool": build_tool,
        "command": display_cmd,
        "testPattern": ",".join(patterns),
        "testPatterns": patterns,
        "task": task,
        "failureClasses": failure_classes,
        "patternQuoted": pattern_q,
        "withCoverage": with_coverage,
        "networkOffline": offline,
        "exitCode": exec_meta["exitCode"],
        "timedOut": exec_meta["timedOut"],
        "passed": total_passed,
        "failed": all_failures,
        "skipped": skipped,
        "testcases": all_testcases,
        "flaky": flaky,
        "reportPaths": sorted(set(os.path.abspath(p) for p in xml_paths)),
        "inputsStable": before == after,
        "coverageDataFresh": data_confirmed,
        "coverageReportPaths": sorted(set(os.path.abspath(p) for p in measured)),
        "executionEvidence": {"path": str(_evidence_path(root)), "id": execution_id},
        "reused": False,
        "nextActions": [] if data_confirmed else ["Confirm the active JaCoCo execution-data paths before accepting coverage; inherited/custom destinations are not guessed."],
        "stdoutTail": exec_meta["stdoutTail"],
        "stderrTail": exec_meta["stderrTail"],
    }


@mcp.tool()
def parse_junit_xml(root: str = ".", build_tool: str = "", task: str | None = None,
                    report_dirs: list[str] | None = None) -> dict:
    """Parse Gradle/Maven JUnit XML reports -> per-method results + classified failures[].

    Gradle: build/test-results/test/*.xml ; Maven: target/surefire-reports/*.xml.
    Each failure is classified TEST_COMPILE_FAILED / TEST_RUNTIME_FAILED / FLAKY_SUSPECTED.

    ``testcases[]`` ({"class", "name", "result": passed|failed|skipped, "flaky"})
    is the per-method machine record: a method-level pass/skip verdict must be
    read from here, never inferred from absence in ``failed[]`` (a @Disabled or
    unexecuted test is also absent there). ``flaky[]`` lists tests that carry
    retry history (Surefire rerunFailure / Gradle mergeReruns flakyFailure)
    even when they eventually passed.
    """
    root = _project_root(root)
    if task is not None:
        if build_tool not in ("gradle", "maven") or not re.fullmatch(r":?[\w-]+(?::[\w-]+)*", task):
            return {"status": "failed", "error": "INVALID_TEST_TASK"}
        if build_tool == "maven" and task not in ("test", "verify"):
            return {"status": "failed", "error": "INVALID_TEST_TASK"}
        xml_paths = _junit_paths(root, build_tool, task, report_dirs)
    else:
        xml_paths = _junit_paths(root, build_tool, task, report_dirs)

    total_passed, all_failures, all_testcases, skipped, flaky = _aggregate_junit(xml_paths)

    if not xml_paths:
        status = "failed"
    elif all_failures:
        status = "partial"
    elif total_passed == 0:
        status = "failed"
    else:
        status = "ok"

    return {
        "status": status,
        "passed": total_passed,
        "failed": all_failures,
        "skipped": skipped,
        "testcases": all_testcases,
        "flaky": flaky,
        "reportPaths": sorted(set(os.path.abspath(p) for p in xml_paths)),
    }


@mcp.tool()
def parse_jacoco_report(root: str = ".", packages: list[str] | None = None,
                        excludes: list[str] | None = None, report_paths: list[str] | None = None,
                        aggregate_report: str | None = None) -> dict:
    """Parse a JaCoCo XML report into per-counter coverage + per-class + uncovered[].

    Gradle: build/reports/jacoco/test/jacocoTestReport.xml ;
    Maven : target/site/jacoco/jacoco.xml.
    Counters: LINE, BRANCH, METHOD, CLASS, INSTRUCTION (overall and per class).
    `uncovered[]` lists classes/methods below target so a coverage-closer can act.

    Multi-module builds are aggregated: when no root-level report exists, every
    submodule report is summed so an unmeasured module cannot pass the gate.
    `reportPaths[]` lists everything that was counted; `reportPath` stays the first.
    """
    root = _project_root(root)
    jacoco_paths = _jacoco_paths(root, report_paths, aggregate_report)
    if not jacoco_paths:
        return {"status": "failed", "error": "JACOCO_REPORT_NOT_FOUND",
                "message": f"no jacoco.xml found under: {root}"}
    return _coverage_result(root, jacoco_paths, packages, excludes, aggregate_report)


@mcp.tool()
def detect_pipeline_state(root: str = ".", line: float = 1.0, branch: float = 1.0,
                          method: float = 1.0, klass: float = 1.0, packages: list[str] | None = None,
                          excludes: list[str] | None = None, report_dirs: list[str] | None = None,
                          report_paths: list[str] | None = None, aggregate_report: str | None = None) -> dict:
    """Reconstruct full-pipeline progress from DURABLE on-disk evidence (not _workspace/).

    `_workspace/` intermediate artifacts are .gitignored and ephemeral, so after a fresh
    clone / git checkout / new session / workspace rotation the pipeline cannot tell that
    tests, approved scenarios, and coverage reports already exist — full-pipeline
    Phase 0 would then misclassify the project as a first run and restart from stage 0.
    This tool scans the durable, committable evidence and maps it to the highest completed
    pipeline stage so Phase 0 can resume at the right stage.

    Evidence -> stage:
      test_docs/refactoring/RA-*.md        -> stage 3.5 (refactor advisory)
      test_docs/scenarios/*.md (approved)  -> stages 4 / 4.5 (scenarios designed + approved)
      src/test/java/**/*Test(s).java       -> stage 5 (tests generated) — ONLY with provenance
      JUnit XML report                     -> stage 6 (tests run)
      JaCoCo XML report                    -> stage 8 (coverage measured)

    PROVENANCE GATE: a bare *Test*.java proves a test exists, not that THIS harness wrote
    it. Harness-authored tests are evidenced by test_docs/ (scenario docs / INDEX.md). When
    tests exist WITHOUT that provenance they are FOREIGN (hand-written / pre-existing):
    `foreignTestsPresent=true`, `harnessProvenance=false`, they do NOT count as stage 5, and
    `recommendedEntryStage` stays 0 (initial run) so the harness still designs+generates
    tests — the pipeline threads foreign tests as existingTestPaths to augment coverage gaps
    without overwriting them. `resumable` means "a harness pipeline left mid-stream state";
    foreign-tests-only is not resumable.

    FRESHNESS GATE: evidence proves a stage RAN ONCE, not that it ran against the
    CURRENT source. If the service code changed after the reports were written, resuming
    on them would report "all scenarios satisfied" without ever executing the change.
    `staleness{}` machine-compares the newest source mtime against each piece of evidence
    (2s tolerance for filesystem timestamp granularity) and `recommendedEntryStage` is
    clamped down accordingly: stale JaCoCo -> 8, stale JUnit -> 6, stale scenarios -> 4,
    a build file newer than the cached HarnessConfig -> 0 (the Spring profile must be
    re-detected). `highestCompletedStage` records what did happen and is not clamped.

    Every probe is fail-safe: any error yields a null/empty field (detection must never
    break the pipeline). Returns
    `highestCompletedStage` + `recommendedEntryStage` so CI has a deterministic default;
    interactive mode may still ask the user which stage to resume from. The coverage
    thresholds default to 1.0 so a root-only durable scan cannot skip stage 8 when the
    previous/current HarnessConfig is unknown. Callers with a schema-v2 config should pass
    its LINE/BRANCH/METHOD/CLASS thresholds explicitly.
    """
    root = _project_root(root)

    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    # --- durable test files (stage 5) ---
    test_files: list[str] = [p for p in _collect_source_files(root) if "/src/test/java/" in p.replace("\\", "/")]
    test_base = os.path.join(root, "src", "test", "java")
    if os.path.isdir(test_base):
        for dirpath, _dirs, files in os.walk(test_base):
            for fn in files:
                if fn.endswith(".java") and ("Test" in fn or fn.endswith("IT.java")):
                    if os.path.join(dirpath, fn) not in test_files:
                        test_files.append(os.path.join(dirpath, fn))
    has_tests = bool(test_files)

    # --- scenarios (stages 4 / 4.5): count test_docs/scenarios/*.md by `approval:` ---
    scen_dir = os.path.join(root, "test_docs", "scenarios")
    scen_paths = _safe(lambda: glob.glob(os.path.join(scen_dir, "*.md")), []) or []
    approved_scen = pending_scen = excluded_scen = 0
    approved_ids: set[str] = set()
    for sp in scen_paths:
        txt = _safe(lambda p=sp: _read_text(p, limit=8000), "") or ""
        m = re.search(r"(?m)^\s*approval:\s*([A-Za-z]+)", txt)
        state = m.group(1).lower() if m else ""
        if state == "approved":
            approved_scen += 1
            id_match = re.search(r"(?m)^\s*(?:id|scenarioId):\s*['\"]?([\w-]+)", txt)
            approved_ids.add(id_match.group(1) if id_match else Path(sp).stem)
        elif state == "excluded":
            excluded_scen += 1
        else:
            pending_scen += 1

    # --- refactor advisories (stage 3.5) ---
    ra_dir = os.path.join(root, "test_docs", "refactoring")
    ra_paths = _safe(lambda: glob.glob(os.path.join(ra_dir, "RA-*.md")), []) or []
    has_index = os.path.isfile(os.path.join(root, "test_docs", "INDEX.md"))

    # --- reports (stages 6 / 8), reusing existing parsers, fail-safe ---
    junit = _safe(lambda: parse_junit_xml(root, report_dirs=report_dirs), None)
    jacoco = _safe(lambda: parse_jacoco_report(root, packages, excludes, report_paths, aggregate_report), None)
    jacoco_gate = _safe(
        lambda: coverage_gate(root, line=line, branch=branch, method=method, klass=klass, packages=packages, excludes=excludes, report_paths=report_paths, aggregate_report=aggregate_report),
        None,
    )

    def _report_ok(r):
        return bool(r) and r.get("status") in ("ok", "partial")

    junit_ok = _report_ok(junit)
    junit_green = (
        isinstance(junit, dict)
        and junit.get("status") == "ok"
        and isinstance(junit.get("passed"), int)
        and not isinstance(junit.get("passed"), bool)
        and junit.get("passed") > 0
        and not junit.get("failed")
    )
    jacoco_ok = _report_ok(jacoco)
    jacoco_gate_ok = (
        jacoco_ok
        and isinstance(jacoco_gate, dict)
        and jacoco_gate.get("status") == "ok"
        and jacoco_gate.get("pass") is True
    )

    junit_summary = {"present": False}
    if isinstance(junit, dict):
        junit_summary = {"present": True, "passed": junit.get("passed", 0),
                         "failed": len(junit.get("failed", []))}
    jacoco_summary = {"present": False}
    if jacoco_ok:
        overall = (jacoco.get("overall") or {})
        jacoco_summary = {"present": True,
                          "line": (overall.get("LINE") or {}).get("ratio"),
                          "branch": (overall.get("BRANCH") or {}).get("ratio"),
                          "gatePassed": jacoco_gate_ok}
    # --- existing _workspace/ artifacts (partial-restore hint) ---
    ws_dir = os.path.join(root, "_workspace")
    ws_artifacts = sorted(
        os.path.basename(p)
        for p in (_safe(lambda: glob.glob(os.path.join(ws_dir, "*.json")), []) or [])
    )

    # --- provenance: did THIS harness author the tests here? ---
    # A bare *Test*.java under src/test/java proves a test exists, NOT that the harness
    # generated it. The harness's own tests are evidenced by test_docs/ (scenario docs or
    # INDEX.md; generated test methods also carry a scenarioRef). Without that provenance,
    # existing tests are FOREIGN (hand-written / pre-existing) and must NOT be treated as
    # "stage 5 complete" — otherwise the harness would skip design+generation and never
    # add tests for uncovered code. Foreign tests are surfaced so generate-tests/coverage
    # can coexist with them (passed as existingTestPaths, no overwrite).
    linked_ids = set()
    for test_file in test_files:
        linked_ids.update(re.findall(r"scenarioRef\s*[:=]\s*['\"]?([\w-]+)", _read_text(test_file)))
    test_provenance = bool(approved_ids & linked_ids)
    foreign_tests_present = has_tests and not test_provenance

    # --- stage inference (highest completed) ---
    # Only harness-authored progress advances the stage; foreign tests/reports do not.
    harness_tests = has_tests and test_provenance
    highest = "none"
    if ra_paths:
        highest = "3.5"
    if approved_scen > 0:
        highest = "4.5"
    if harness_tests:
        highest = "5"
    if harness_tests and junit_ok:
        highest = "6"
    if harness_tests and jacoco_ok:
        highest = "8"
    # recommended entry stage (deterministic CI default):
    #  - green JUnit + JaCoCo gate evidence -> re-verify conformance at stage 9.
    #  - green JUnit evidence -> re-measure coverage at stage 8.
    #  - failed/partial or missing JUnit -> rerun tests at stage 6.
    #  - harness-authored tests exist -> rerun tests at stage 6, no regeneration.
    #  - scenarios approved but tests missing -> enter at 5(generate).
    #  - foreign-tests-only OR nothing durable -> initial full run (stage 0). When foreign
    #    tests are present, the pipeline threads them as existingTestPaths so generate-tests
    #    augments coverage gaps instead of clobbering the hand-written tests.
    if harness_tests and junit_green and jacoco_gate_ok:
        recommended = 9
    elif harness_tests and junit_green:
        recommended = 8
    elif harness_tests:
        recommended = 6
    elif approved_scen > 0:
        recommended = 5
    else:
        recommended = 0

    # --- freshness: evidence proves a stage RAN, not that it ran against THIS source ---
    # A report older than the source it covers says nothing about the current code, so
    # resuming past the stage that produced it would report success without ever
    # executing the change. Clamp the entry stage down to the earliest stage whose
    # evidence is still trustworthy. `highestCompletedStage` is a record of what did
    # happen and is deliberately left alone.
    staleness = _safe(lambda: _compute_staleness(root), {}) or {}
    stale_reasons: list[str] = []
    if staleness.get("sourceNewerThanJacoco") and recommended > 8:
        recommended = 8
        stale_reasons.append("JACOCO_STALE")
    if staleness.get("sourceNewerThanJunit") and recommended > 6:
        recommended = 6
        stale_reasons.append("JUNIT_STALE")
    if staleness.get("sourceNewerThanScenarios") and recommended > 4:
        recommended = 4
        stale_reasons.append("SCENARIOS_STALE")
    if staleness.get("buildFileNewerThanConfig"):
        # A changed build file can move the whole Spring profile (javax<->jakarta,
        # junit4<->jupiter, @MockBean<->@MockitoBean). Stage 0 must re-detect it before
        # anything downstream reuses the cached HarnessConfig.
        recommended = 0
        stale_reasons.append("CONFIG_STALE")
    try:
        previous = json.loads(_evidence_path(root).read_text(encoding="utf-8")).get("inputs", {})
        current = _input_snapshot(root)
        changed = [p for p in previous.keys() | current.keys() if previous.get(p) != current.get(p)]
        if any(Path(p).name in _BUILD_FILES or p.startswith(("gradle/", "buildSrc/")) for p in changed):
            recommended = 0
            stale_reasons.append("BUILD_CONTENT_CHANGED")
        elif any(p.startswith(("docs/", "specs/", "requirements/", "test_docs/scenarios/")) or "/src/main/java/" in "/" + p for p in changed):
            recommended = min(recommended, 4)
            stale_reasons.append("SCENARIO_INPUT_CONTENT_CHANGED")
    except (OSError, ValueError, TypeError):
        pass
    if pending_scen:
        recommended = min(recommended, 4)
        stale_reasons.append("SCENARIO_APPROVAL_REQUIRED")
    if approved_ids - linked_ids and recommended > 5:
        recommended = 5
        stale_reasons.append("SCENARIO_TEST_MAPPING_INCOMPLETE")
    if recommended > 6:
        fresh, reason = _fresh_run(root, (junit or {}).get("reportPaths", []))
        if not fresh:
            recommended = 6
            stale_reasons.append(reason)
    if recommended > 8:
        fresh, reason = _fresh_run(root, (jacoco or {}).get("reportPaths", []), coverage=True)
        if not fresh:
            recommended = 8
            stale_reasons.append(reason)
    staleness["stale"] = bool(stale_reasons)
    staleness["reasons"] = stale_reasons

    # resumable = a harness pipeline actually left mid-stream state to resume from.
    # Foreign-tests-only is NOT resumable (there is no harness stage to resume).
    resumable = harness_tests or approved_scen > 0 or bool(ra_paths)

    return {
        "status": "ok",
        "root": root,
        "resumable": resumable,
        "harnessProvenance": test_provenance,
        "foreignTestsPresent": foreign_tests_present,
        "hasTests": has_tests,
        "testFileCount": len(test_files),
        "testFiles": sorted(test_files)[:200],
        "hasTestDocsIndex": has_index,
        "scenarios": {
            "approved": approved_scen,
            "pending": pending_scen,
            "excluded": excluded_scen,
            "total": len(scen_paths),
        },
        "refactorAdvisories": len(ra_paths),
        "junitReport": junit_summary,
        "jacocoReport": jacoco_summary,
        "staleness": staleness,
        "workspaceArtifacts": ws_artifacts,
        "highestCompletedStage": highest,
        "recommendedEntryStage": recommended,
        "evidence": {
            "testDir": test_base if has_tests else None,
            "scenarioDir": scen_dir if scen_paths else None,
            "refactorDir": ra_dir if ra_paths else None,
            "junitReportPaths": (junit.get("reportPaths") if junit_ok else []) or [],
            "jacocoPath": _safe(lambda: _find_jacoco_xml(root), None),
        },
    }


@mcp.tool()
def coverage_gate(root: str = ".", line: float = DEFAULT_LINE, branch: float = DEFAULT_BRANCH,
                  method: float = DEFAULT_METHOD, klass: float = DEFAULT_CLASS,
                  packages: list[str] | None = None, excludes: list[str] | None = None,
                  report_paths: list[str] | None = None, aggregate_report: str | None = None,
                  require_fresh: bool = False, java_home: str | None = None) -> dict:
    """Parse JaCoCo and return pass/fail per counter plus actionable gaps.

    Returns overall pass flag plus a per-counter breakdown with the actual ratio,
    the required threshold, and pass/fail. Includes uncovered classes and methods
    as actionable gaps.

    Note: `klass` (CLASS counter) defaults to 1.0 per the near-100% policy. On a
    narrowly-targeted run whose JaCoCo report scope still includes uncovered sibling
    classes, the overall CLASS ratio can be <1.0 and fail the gate; use packages/excludes to scope the report. Never lower thresholds to compensate for scope.
    """
    root = _project_root(root)

    jacoco_paths = _jacoco_paths(root, report_paths, aggregate_report)
    jacoco_path = jacoco_paths[0] if jacoco_paths else None

    counters_result: dict[str, dict] = {}
    gaps: dict = {"uncovered": []}
    missing: list[str] = []

    if not jacoco_paths:
        missing.append("JACOCO_REPORT_NOT_FOUND")
    else:
        jr = _coverage_result(root, jacoco_paths, packages, excludes, aggregate_report)
        if jr.get("status") != "ok":
            missing.append(jr.get("error", "JACOCO_PARSE_FAILED"))
        else:
            overall = jr["overall"]
            wanted = {"LINE": line, "BRANCH": branch, "METHOD": method, "CLASS": klass}
            for ctype, threshold in wanted.items():
                actual = overall.get(ctype, {}).get("ratio")
                if ctype == "BRANCH" and actual is None and jr.get("perClass") and all(overall.get(k, {}).get("covered", 0) + overall.get(k, {}).get("missed", 0) > 0 for k in ("LINE", "METHOD", "CLASS")):
                    counters_result[ctype] = {"actual": None, "threshold": threshold, "pass": True,
                                               "applicable": False, "note": "Valid measured code has no branches"}
                    continue
                if actual is None:
                    counters_result[ctype] = {
                        "actual": None, "threshold": threshold,
                        "pass": False, "note": "counter absent in report",
                    }
                else:
                    counters_result[ctype] = {
                        "actual": actual, "threshold": threshold,
                        "pass": actual >= threshold,
                    }
            gaps["uncovered"] = jr["uncovered"]

    fresh, stale_reason = _fresh_run(root, jacoco_paths, coverage=True, java_home=java_home)
    if require_fresh and not fresh:
        missing.append(stale_reason)
    all_pass = bool(counters_result) and not missing and all(c["pass"] for c in counters_result.values())

    if not counters_result:
        status = "failed"
    elif all_pass and not missing:
        status = "ok"
    else:
        status = "partial"

    return {
        "status": status,
        "pass": all_pass,
        "counters": counters_result,
        "gaps": gaps,
        "missingReports": missing,
        "jacocoPath": jacoco_path,
        "reportPaths": jacoco_paths,
        "evidenceFresh": fresh,
        "stalenessReason": stale_reason or None,
        "executionEvidence": {"path": str(_evidence_path(root))},
    }


# ---------------------------------------------------------------------------
# Build-capability provisioning (F1) + dependency-cache priming (F2)
#
# These tools EXPOSE SIGNALS ONLY (no file writes). JaCoCo XML is required for stage 8.
# Per fallback-policy.md #17/#18 the consuming skill detects required gaps, asks for
# approval (interactive) or stops with remediation (CI), then applies the minimal build
# change itself. Sources: references/build-provisioning.md.
# ---------------------------------------------------------------------------

# JaCoCo XML toggle is OFF by default for the Gradle plugin, so the harness's
# parse_jacoco_report finds no jacoco.xml unless this is set explicitly.
_GRADLE_JACOCO_PLUGIN_RE = re.compile(r"""(?:id\s*\(?\s*['"]jacoco['"]|apply\s+plugin:\s*['"]jacoco['"])""")
_GRADLE_JACOCO_XML_RE = re.compile(r"""xml\s*\.\s*(?:required|enabled)\s*(?:\.\s*set\s*\(\s*)?=?\s*true""")
_MAVEN_JACOCO_RE = re.compile(r"""jacoco-maven-plugin""")
_MAVEN_JACOCO_REPORT_GOAL_RE = re.compile(r"""<goal>\s*report\s*</goal>""")


def _gradle_build_text(root: str) -> tuple[str, str]:
    """Return (build-file text, build-file name) for Gradle (.kts preferred)."""
    for name in ("build.gradle.kts", "build.gradle"):
        text = _read_text(os.path.join(root, name))
        if text:
            return _strip_build_comments(text), name
    return "", ""


def _gradle_capabilities(root: str) -> tuple:
    """Return required JaCoCo capabilities and changes for a Gradle target build."""
    text, fname = _gradle_build_text(root)
    kts = fname.endswith(".kts")
    wrapper = _read_text(os.path.join(root, "gradle/wrapper/gradle-wrapper.properties"))
    version = re.search(r"gradle-(\d+)\.(\d+)", wrapper)
    modern_reports = not version or tuple(map(int, version.groups())) >= (6, 1)
    fref = fname or "build.gradle[.kts]"
    caps = {
        "jacoco": bool(_GRADLE_JACOCO_PLUGIN_RE.search(text)),
        "jacocoXml": bool(_GRADLE_JACOCO_XML_RE.search(text)),
    }
    missing: list[str] = []
    proposed: list[dict] = []
    if not caps["jacoco"]:
        missing.append("JACOCO_PLUGIN_MISSING")
        proposed.append({
            "file": fref,
            "anchor": "plugins { }",
            "snippet": ('id("jacoco")' if kts else "id 'jacoco'"),
            "reason": "Gradle JaCoCo 플러그인 미적용 → jacocoTestReport 태스크 없음",
            "source": "https://docs.gradle.org/current/userguide/jacoco_plugin.html",
        })
    if not caps["jacocoXml"]:
        missing.append("JACOCO_XML_DISABLED")
        proposed.append({
            "file": fref,
            "anchor": "tasks.named('jacocoTestReport') / tasks.jacocoTestReport",
            "snippet": (
                'tasks.jacocoTestReport { reports { xml.required.set(true) } }'
                if kts and modern_reports else
                'tasks.jacocoTestReport { reports { xml.isEnabled = true } }'
                if kts else
                "tasks.named('jacocoTestReport') { reports { xml.required = true } }"
                if modern_reports else
                "jacocoTestReport { reports { xml.enabled = true } }"
            ),
            "reason": "JaCoCo XML 기본 OFF → parse_jacoco_report가 XML 미발견(HTML만 생성)",
            "source": "https://docs.gradle.org/current/userguide/jacoco_plugin.html",
        })
    return caps, missing, proposed


def _maven_jacoco_flags(element: ET.Element | None) -> dict:
    plugins = element.findall("./build/plugins/plugin") if element is not None else []
    plugin = next((p for p in plugins if p.findtext("artifactId") == "jacoco-maven-plugin"
                   and p.findtext("groupId", "org.jacoco") == "org.jacoco"), None)
    flags = {"jacoco": False, "jacocoXml": False}
    if plugin is None:
        return flags
    skip = _pom_value(element, plugin.findtext("./configuration/skip", "false"))
    if skip is None or skip.lower() == "true":
        return flags
    for execution in plugin.findall("./executions/execution"):
        raw_phase = execution.findtext("phase", "")
        phase = _pom_value(element, raw_phase) if raw_phase.strip() else ""
        if phase is None or phase.strip() not in {"", "validate", "initialize", "generate-sources", "process-sources",
                "generate-resources", "process-resources", "compile", "process-classes", "generate-test-sources",
                "process-test-sources", "generate-test-resources", "process-test-resources", "test-compile",
                "process-test-classes", "test", "prepare-package", "package", "pre-integration-test",
                "integration-test", "post-integration-test", "verify"}:
            continue
        skip = _pom_value(element, execution.findtext("./configuration/skip", "false"))
        if skip is None or skip.lower() == "true":
            continue
        goals = {g.text for g in execution.findall("./goals/goal")}
        flags["jacoco"] |= "prepare-agent" in goals
        if "report" in goals:
            formats = execution.findall("./configuration/formats/format") or plugin.findall("./configuration/formats/format")
            flags["jacocoXml"] |= not formats or any((f.text or "").strip().upper() == "XML" for f in formats)
    flags["jacocoXml"] &= flags["jacoco"]
    return flags


def _maven_capabilities(root: str) -> tuple:
    """Return required JaCoCo capabilities and changes for a Maven target build."""
    element, _ = _pom(root)
    caps = _maven_jacoco_flags(element)
    missing: list[str] = []
    proposed: list[dict] = []
    if not caps["jacoco"] or not caps["jacocoXml"]:
        missing.append("JACOCO_PLUGIN_MISSING" if not caps["jacoco"] else "JACOCO_REPORT_GOAL_MISSING")
        proposed.append({
            "file": "pom.xml",
            "anchor": "<build><plugins>",
            "snippet": (
                "<plugin><groupId>org.jacoco</groupId>"
                "<artifactId>jacoco-maven-plugin</artifactId><version>0.8.15</version>"
                "<executions>"
                "<execution><id>prepare-agent</id><goals><goal>prepare-agent</goal></goals></execution>"
                "<execution><id>report</id><phase>verify</phase><goals><goal>report</goal></goals></execution>"
                "</executions></plugin>"
            ),
            "reason": "jacoco-maven-plugin prepare-agent+report 미바인딩 → jacoco.xml 미생성",
            "source": "https://www.eclemma.org/jacoco/trunk/doc/maven.html",
        })
    return caps, missing, proposed


@mcp.tool()
def detect_build_capabilities(root: str = ".", java_home: str | None = None) -> dict:
    """Detect required JaCoCo XML capabilities (signal only).

    The coverage gate (parse_jacoco_report) needs a JaCoCo **XML** report, but the Gradle
    JaCoCo plugin emits HTML only by default (`reports { xml.required = true }` required);
    this tool reads the build file and reports each capability plus a minimal, source-cited
    ``proposedChanges[]`` snippet for required gaps. It does NOT modify any file.

    Returns {status, buildTool, capabilities{jacoco,jacocoXml}, missing[],
    proposedChanges[], remediation}.
    """
    root = _project_root(root)
    det = _detect(root)
    if det.get("status") != "ok":
        return det
    tool = det["buildTool"]

    if tool == "gradle":
        caps, missing, proposed = _gradle_capabilities(root)
        context = _gradle_context(root, java_home)
        if context:
            reports = [r for m in context["modules"] for r in m["coverageReports"]]
            caps = {"jacoco": bool(reports), "jacocoXml": bool(reports) and all(r["xmlEnabled"] for r in reports)}
            missing = [name for flag, name in (("jacoco", "JACOCO_PLUGIN_MISSING"), ("jacocoXml", "JACOCO_XML_DISABLED")) if not caps[flag]]
            proposed = [p for p in proposed if missing]
    else:  # maven
        caps, missing, proposed = _maven_capabilities(root)
        effective = _effective_pom(root, java_home)
        if effective is not None:
            caps = _maven_jacoco_flags(effective)
            missing = ([] if caps["jacocoXml"] else ["JACOCO_BINDINGS_INCOMPLETE"])
    verified = (context is not None) if tool == "gradle" else effective is not None
    unicode_agent = None
    if tool == "maven" and os.name == "nt" and not root.isascii():
        repository = None
        if effective is not None:
            try:
                probe = _run_subprocess(_platform_command([_launcher("maven", root), "-o", "-q", "help:evaluate",
                                        "-Dexpression=settings.localRepository", "-DforceStdout"]), root, java_home)
                output = re.sub(r"\x1b\[[\d;]*m", "", probe.get("stdout", "")).strip()
                if probe["exitCode"] == 0 and Path(output).is_absolute() and Path(output).is_dir():
                    repository = output
            except (OSError, ValueError):
                pass
        unicode_agent = _windows_maven_agent_proposal(root, effective, repository)
        if unicode_agent.get("change"):
            proposed.append(unicode_agent["change"])

    all_ok = not missing
    remediation = ("" if all_ok else
                   "메인 대화: AskUserQuestion 승인 후 proposedChanges[]를 빌드 파일에 주입(buildChanges[]에 기록). "
                   "CI: 누락 항목과 위 스니펫을 remediation으로 보고하고 중단(HarnessRequest 사전 제공). "
                   "근거·전체 스니펫: references/build-provisioning.md")
    return {
        "status": "ok" if all_ok else "partial",
        "buildTool": tool,
        "capabilities": caps,
        "configurationVerified": verified,
        "windowsMavenAgent": unicode_agent,
        "missing": missing,
        "proposedChanges": proposed,
        "remediation": remediation,
    }


def _windows_maven_agent_proposal(root: str, effective: ET.Element | None, repository: str | None = None) -> dict:
    """A reviewable setup proposal only; never overwrite a caller's JVM args."""
    result = {"status": "confirmation_required", "reason": "WINDOWS_UNICODE_AGENT_DESTFILE",
              "source": "https://github.com/jacoco/jacoco/issues/1735"}
    if effective is None or repository is None:
        return dict(result, detail="Obtain effective POM, JVM argLine and module workingDirectory before applying a workaround.")
    plugins = effective.findall("./build/plugins/plugin")
    jacoco = next((p for p in plugins if p.findtext("artifactId") == "jacoco-maven-plugin"), None)
    if jacoco is None or len(_module_dirs(root)) != 1:
        return dict(result, detail="Confirm each module's agent/report path independently.")
    config = jacoco.find("configuration")
    if config is None:
        config = ET.Element("configuration")
    known = {"destFile", "append", "includes", "excludes", "exclClassLoaders", "inclBootstrapClasses",
             "inclNoLocationClasses", "sessionId", "dumpOnExit", "output", "address", "port", "classDumpDir", "jmx", "skip", "propertyName"}
    if any(n.tag not in known for n in config) or any(e.find("configuration") is not None for e in jacoco.findall("./executions/execution")):
        return dict(result, detail="Agent execution options need manual resolution; no automatic replacement proposed.")
    property_name = config.findtext("propertyName", "argLine")
    destination = config.findtext("destFile", str(Path(root) / "target/jacoco.exec"))
    try:
        relative = scoped_path(root, destination).relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return dict(result, detail="Agent data path is outside the module; confirm an approved ASCII destination and report dataFile together.")
    if not relative.isascii() or "${" in relative:
        return dict(result, detail="An ASCII relative data path could not be established.")
    options = ["destfile=" + relative]
    mapping = {"append": "append", "includes": "includes", "excludes": "excludes", "exclClassLoaders": "exclclassloader",
               "inclBootstrapClasses": "inclbootstrapclasses", "inclNoLocationClasses": "inclnolocationclasses",
               "sessionId": "sessionid", "dumpOnExit": "dumponexit", "output": "output", "address": "address", "port": "port", "classDumpDir": "classdumpdir", "jmx": "jmx"}
    for key, option in mapping.items():
        node = config.find(key)
        if node is not None:
            value = ":".join((c.text or "") for c in node) if list(node) else (node.text or "")
            if "${" in value or any(c in value for c in ',"\n\r'):
                return dict(result, detail="Agent options are unresolved; preserve them manually before applying the workaround.")
            options.append(option + "=" + value)
    version = jacoco.findtext("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return dict(result, detail="Resolve the active JaCoCo agent version first.")
    replacements = []
    for plugin in plugins:
        if plugin.findtext("artifactId") not in {"maven-surefire-plugin", "maven-failsafe-plugin"}:
            continue
        if any(e.find("./configuration/argLine") is not None or e.find("./configuration/workingDirectory") is not None
               for e in plugin.findall("./executions/execution")):
            return dict(result, detail="Resolve execution-level JVM arguments and workingDirectory before proposing a replacement.")
        cwd = plugin.findtext("./configuration/workingDirectory", root)
        if os.path.normcase(os.path.realpath(cwd)) != os.path.normcase(os.path.realpath(root)):
            return dict(result, detail="Test workingDirectory differs from the module; relative paths require manual confirmation.")
        args = plugin.findtext("./configuration/argLine", effective.findtext("./properties/" + property_name, ""))
        reference = "@{" + property_name + "}"
        if (property_name in args and reference not in args) or "-javaagent:" in args or "${" in args:
            return dict(result, detail="Existing JVM/agent arguments need manual resolution; no replacement proposed.")
        property_args = effective.findtext("./properties/" + property_name, "")
        if reference in args and ("${" in property_args or "@{" in property_args or "-javaagent:" in property_args):
            return dict(result, detail="Resolve the original late-bound JVM property before proposing a replacement.")
        agent = Path(repository) / f"org/jacoco/org.jacoco.agent/{version}/org.jacoco.agent-{version}-runtime.jar"
        if not agent.is_file():
            return dict(result, detail="Resolve the actual runtime agent artifact from the configured Maven repository first.")
        agent_arg = '"-javaagent:' + agent.as_posix() + "=" + ",".join(options) + '"'
        rewritten = args.replace(reference, (agent_arg + " " + property_args).strip()) if reference in args else (agent_arg + " " + args).strip()
        from xml.sax.saxutils import escape
        replacements.append(plugin.findtext("artifactId") + ": <argLine>" + escape(rewritten) + "</argLine>")
    if not replacements:
        return dict(result, detail="Resolve the active Surefire/Failsafe plugins first.")
    return dict(result, preservedJvmArgs=True, workingDirectory=root, relativeDestFile=relative,
                change={"file": "pom.xml", "anchor": "existing Surefire/Failsafe configuration/argLine (merge, do not replace plugins)",
                        "snippet": "\n".join(replacements), "reason": "Use ASCII relative JaCoCo destfile while retaining resolved agent options and JVM arguments; existing setup approval is required.",
                        "source": result["source"]})


@mcp.tool()
def check_dependency_cache(build_tool: str = "", root: str = ".") -> dict:
    """Best-effort signal: is the dependency cache likely PRIMED, or COLD? (F2, signal only).

    Network is OFF by default (`--offline`/`-o`), and Gradle fails fast when a required
    module is not cached. A cold cache (or a build file just given a new JaCoCo plugin)
    therefore breaks the first offline run. This heuristic checks the shared
    Gradle/Maven caches; it cannot guarantee per-project completeness, so when COLD it
    recommends a one-time online priming run (run_targeted_tests(online=True)) gated by
    approval (fallback-policy.md #18). It does NOT touch the network or any file.

    Returns {status, buildTool, primed, evidence, primeCommand, recommendation}.
    """
    root = _project_root(root)
    tool = (build_tool or "").strip().lower()
    if tool not in ("gradle", "maven"):
        det = _detect(root)
        tool = det.get("buildTool", "none")
    home = os.path.expanduser("~")
    primed = False
    evidence = ""
    prime_cmd = ""
    if tool == "gradle":
        modules = os.path.join(home, ".gradle", "caches", "modules-2", "files-2.1")
        primed = os.path.isdir(modules) and bool(os.listdir(modules))
        evidence = f"~/.gradle/caches/modules-2/files-2.1 present={primed}"
        prime_cmd = "한 번 online 실행: run_targeted_tests(online=True) — Gradle은 첫 실행에서 의존성/플러그인 해석"
    elif tool == "maven":
        repo = os.path.join(home, ".m2", "repository")
        primed = os.path.isdir(repo) and bool(os.listdir(repo))
        evidence = f"~/.m2/repository present={primed}"
        prime_cmd = "mvn dependency:go-offline (의존성+플러그인 일괄 다운로드) 또는 run_targeted_tests(online=True)"
    else:
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"unsupported build_tool: {build_tool!r}"}
    return {
        "status": "ok",
        "buildTool": tool,
        "primed": primed,
        "evidence": evidence,
        "primeCommand": prime_cmd,
        "recommendation": (
            "오프라인 실행 진행 가능(캐시 추정 PRIMED). 단 플러그인을 새로 추가했다면 1회 priming 권장."
            if primed else
            "캐시 COLD 추정 → 첫 실행이 --offline 의존성 해석 실패 위험. 대화형=승인 후 1회 online priming, "
            "CI=BUILD_TEST_ALLOW_NETWORK=1 옵트인 또는 사전 캐시 워밍업. 근거: Gradle Dependency Caching."
        ),
    }


def main() -> None:
    """Entry point: run the build-test server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
