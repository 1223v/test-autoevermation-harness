#!/usr/bin/env python3
"""build_test_server.py — REAL build-test MCP server (coverage/mutation-aware engine).

FastMCP server named "build-test". Coverage/mutation-aware test execution engine for
the Spring test-harness plugin.

Design source of truth:
  - RESEARCH_NOTES.md  (§1 FastMCP API, §3 JaCoCo 0.8.12, §4 PITest, §6 near-100% policy)
  - REPORT.md          (build-test-mcp design + TestRunResult schema)
  - scripts/detect-build-tool.sh, scripts/collect-test-reports.py (heuristics reused)

Standard library only (subprocess, xml.etree, json, os, shlex). Python 3.10+.

Security posture (REPORT.md §권한과 보안, RESEARCH_NOTES §build-test-mcp):
  - All shell arguments are shlex-quoted.
  - Targeted/narrowest test scope by default.
  - Network is OFF by default (gradle --offline, maven -o) unless
    BUILD_TEST_ALLOW_NETWORK=1 is set in the environment.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("build-test")

# ---------------------------------------------------------------------------
# Constants / policy defaults
# ---------------------------------------------------------------------------

# Default coverage gate thresholds (RESEARCH_NOTES §6 near-100% policy).
DEFAULT_LINE = 0.95
DEFAULT_BRANCH = 0.90
DEFAULT_METHOD = 0.95
DEFAULT_CLASS = 1.0
DEFAULT_MUTATION = 0.80

# Subprocess wall-clock cap (seconds) so a hung build can't block the server.
_RUN_TIMEOUT = 1800

# Failure-classification heuristics (reused from collect-test-reports.py).
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
    """Network is OFF by default; only ON when BUILD_TEST_ALLOW_NETWORK is truthy."""
    val = os.environ.get("BUILD_TEST_ALLOW_NETWORK", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _detect(root: str) -> dict:
    """Core build-tool detection. Returns {buildTool, wrapper} or BUILD_TOOL_UNDETECTED.

    Mirrors scripts/detect-build-tool.sh: prefer wrapper, then standard build files,
    Gradle before Maven.
    """
    if not os.path.isdir(root):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"directory not found: {root}"}

    tool = "none"
    wrapper = False

    if os.path.isfile(os.path.join(root, "gradlew")):
        tool, wrapper = "gradle", True
    elif (os.path.isfile(os.path.join(root, "build.gradle"))
          or os.path.isfile(os.path.join(root, "build.gradle.kts"))):
        tool, wrapper = "gradle", False
    elif os.path.isfile(os.path.join(root, "mvnw")):
        tool, wrapper = "maven", True
    elif os.path.isfile(os.path.join(root, "pom.xml")):
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


def _find_junit_xml(root: str) -> list[str]:
    """Locate JUnit XML reports for Gradle and Maven (incl. one level of submodules)."""
    patterns = [
        os.path.join(root, "build", "test-results", "test", "*.xml"),
        os.path.join(root, "target", "surefire-reports", "*.xml"),
        os.path.join(root, "target", "failsafe-reports", "*.xml"),
        os.path.join(root, "*", "build", "test-results", "test", "*.xml"),
        os.path.join(root, "*", "target", "surefire-reports", "*.xml"),
        os.path.join(root, "*", "target", "failsafe-reports", "*.xml"),
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(glob.glob(pattern))
    return found


def _parse_junit_file(path: str) -> tuple[int, list[dict]]:
    """Parse one JUnit XML file -> (passed_count, failures[])."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return 0, [{"test": path, "type": "TEST_RUNTIME_FAILED",
                    "message": f"XML parse error: {exc}"}]

    root_el = tree.getroot()
    if root_el.tag == "testsuites":
        suites = list(root_el.findall("testsuite"))
    elif root_el.tag == "testsuite":
        suites = [root_el]
    else:
        suites = list(root_el.iter("testsuite"))

    passed = 0
    failures: list[dict] = []
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
                    "type": _classify_failure(ftype, fmsg),
                    "message": fmsg[:500],
                })
            elif skipped_el is None:
                passed += 1
    return passed, failures


def _find_jacoco_xml(root: str) -> str | None:
    """Locate jacoco.xml for Gradle or Maven (incl. one level of submodules)."""
    candidates = [
        os.path.join(root, "build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
        os.path.join(root, "target", "site", "jacoco", "jacoco.xml"),
        os.path.join(root, "*", "build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
        os.path.join(root, "*", "target", "site", "jacoco", "jacoco.xml"),
    ]
    for pat in candidates:
        if os.path.sep in pat and "*" in pat:
            matches = glob.glob(pat)
            if matches:
                return matches[0]
        elif os.path.isfile(pat):
            return pat
    # Last-resort broad search.
    broad = glob.glob(os.path.join(root, "**", "jacoco*.xml"), recursive=True)
    return broad[0] if broad else None


def _counter_ratio(missed: int, covered: int) -> float:
    total = missed + covered
    return (covered / total) if total > 0 else 1.0


def _parse_jacoco(jacoco_path: str) -> dict:
    """Parse a JaCoCo XML report -> per-counter coverage + per-class + uncovered[]."""
    try:
        tree = ET.parse(jacoco_path)
    except ET.ParseError as exc:
        return {"status": "failed", "error": "JACOCO_PARSE_FAILED",
                "message": f"XML parse error: {exc}", "reportPath": jacoco_path}

    root_el = tree.getroot()  # <report>

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

    for package in root_el.findall("package"):
        pkg_name = package.get("name", "")
        for clazz in package.findall("class"):
            cls_name = clazz.get("name", "")
            fqcn = cls_name.replace("/", ".")
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
                if m_missed > 0:
                    uncovered_methods.append({
                        "method": method.get("name", ""),
                        "desc": method.get("desc", ""),
                        "line": int(method.get("line", "0")),
                        "missedLines": m_missed,
                        "branchRatio": m_counters.get("BRANCH", {}).get("ratio", 1.0),
                    })

            if line_ratio < DEFAULT_LINE or branch_ratio < DEFAULT_BRANCH \
                    or method_ratio < DEFAULT_METHOD or uncovered_methods:
                uncovered.append({
                    "class": fqcn,
                    "lineRatio": line_ratio,
                    "branchRatio": branch_ratio,
                    "methodRatio": method_ratio,
                    "uncoveredMethods": uncovered_methods,
                })

    return {
        "status": "ok",
        "reportPath": jacoco_path,
        "overall": overall,
        "perClass": per_class,
        "uncovered": uncovered,
    }


def _find_pitest_xml(root: str) -> str | None:
    """Locate PITest mutations.xml for Gradle or Maven (incl. one submodule level)."""
    candidates = [
        os.path.join(root, "build", "reports", "pitest", "mutations.xml"),
        os.path.join(root, "target", "pit-reports", "mutations.xml"),
        os.path.join(root, "*", "build", "reports", "pitest", "mutations.xml"),
        os.path.join(root, "*", "target", "pit-reports", "mutations.xml"),
    ]
    for pat in candidates:
        if "*" in pat:
            matches = glob.glob(pat)
            if matches:
                return matches[0]
        elif os.path.isfile(pat):
            return pat
    broad = glob.glob(os.path.join(root, "**", "mutations.xml"), recursive=True)
    return broad[0] if broad else None


def _parse_pitest(pitest_path: str) -> dict:
    """Parse a PITest mutations.xml -> mutationScore + survivedMutants[]."""
    try:
        tree = ET.parse(pitest_path)
    except ET.ParseError as exc:
        return {"status": "failed", "error": "PITEST_PARSE_FAILED",
                "message": f"XML parse error: {exc}", "reportPath": pitest_path}

    root_el = tree.getroot()  # <mutations>
    total = 0
    killed = 0
    survived_mutants: list[dict] = []

    # status values: KILLED, SURVIVED, NO_COVERAGE, TIMED_OUT, MEMORY_ERROR, RUN_ERROR
    _surviving_statuses = ("SURVIVED", "NO_COVERAGE")

    for mut in root_el.findall("mutation"):
        total += 1
        status = (mut.get("status") or "").upper()
        if status == "KILLED" or status == "TIMED_OUT":
            killed += 1

        if status in _surviving_statuses:
            def _text(tag: str) -> str:
                el = mut.find(tag)
                return el.text if el is not None and el.text is not None else ""

            survived_mutants.append({
                "class": _text("mutatedClass"),
                "method": _text("mutatedMethod"),
                "line": int(_text("lineNumber") or "0"),
                "mutator": _text("mutator"),
                "status": status,
                "description": _text("description"),
            })

    mutation_score = round((killed / total), 6) if total > 0 else 1.0

    return {
        "status": "ok",
        "reportPath": pitest_path,
        "mutationScore": mutation_score,
        "totalMutations": total,
        "killed": killed,
        "survived": len(survived_mutants),
        "survivedMutants": survived_mutants,
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
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _detect_boot_version(root: str) -> tuple[str | None, str]:
    """Best-effort Spring Boot version from build files. Returns (version|None, source)."""
    for name in ("build.gradle.kts", "build.gradle"):
        text = _read_text(os.path.join(root, name))
        if text:
            m = _BOOT_GRADLE_RE.search(text) or _BOOT_GRADLE_CLASSPATH_RE.search(text)
            if m:
                return m.group(1), name
    props = _read_text(os.path.join(root, "gradle.properties"))
    if props:
        m = _BOOT_PROP_RE.search(props)
        if m:
            return m.group(1), "gradle.properties"
    pom = _read_text(os.path.join(root, "pom.xml"))
    if pom:
        m = _BOOT_MAVEN_PARENT_RE.search(pom) or _BOOT_MAVEN_DEPS_RE.search(pom)
        if m:
            return m.group(1), "pom.xml"
    return None, ""


def _scan_imports(root: str, subdir: str, needles: tuple[str, ...],
                  max_files: int = 400) -> dict:
    """Count Java files under root/subdir containing each needle substring."""
    counts = {n: 0 for n in needles}
    base = os.path.join(root, *subdir.split("/"))
    if not os.path.isdir(base):
        return counts
    seen = 0
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            if not fn.endswith(".java"):
                continue
            seen += 1
            if seen > max_files:
                return counts
            text = _read_text(os.path.join(dirpath, fn), limit=60_000)
            for n in needles:
                if n in text:
                    counts[n] += 1
    return counts


def _profile_from_version(bv: str | None) -> dict:
    """Derive the idiom axes from a Boot version string (None => 'latest' 4.x assumption)."""
    major = minor = 0
    if bv:
        parts = bv.split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            major = minor = 0
    if major == 0:
        major = 4  # unknown -> assume latest; caller flags degraded
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
    }


def _run_subprocess(cmd: list[str], cwd: str) -> dict:
    """Run a subprocess with network-off env merge; return execution metadata."""
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT,
        )
        return {
            "exitCode": proc.returncode,
            "stdoutTail": proc.stdout[-4000:] if proc.stdout else "",
            "stderrTail": proc.stderr[-4000:] if proc.stderr else "",
            "timedOut": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exitCode": -1,
            "stdoutTail": (exc.stdout or "")[-4000:] if exc.stdout else "",
            "stderrTail": (exc.stderr or "")[-4000:] if exc.stderr else "",
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

@mcp.tool()
def detect_build_tool(root: str = ".") -> dict:
    """Detect whether the project root uses Gradle or Maven (wrapper aware).

    Returns {status, buildTool, wrapper} or a BUILD_TOOL_UNDETECTED failure.
    """
    return _detect(os.path.abspath(root))


@mcp.tool()
def detect_spring_profile(root: str = ".") -> dict:
    """Detect the target's Spring Boot version profile for version-aware test generation.

    Reads build.gradle[.kts]/pom.xml/gradle.properties for the Boot version, scans
    src/main for javax vs jakarta imports and src/test for the JUnit engine, then derives
    namespace, junitEngine, mockAnnotation/mockImport, javaBaseline and gradleTestMode.
    Supports Boot 2.0–4.x. Returns springProfile.degraded=true when the version cannot be
    detected (caller should interview interactively or assume the latest profile + warn).
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return {"status": "failed", "error": "PROJECT_ROOT_NOT_FOUND",
                "message": f"directory not found: {root}"}

    bv, bv_source = _detect_boot_version(root)
    prof = _profile_from_version(bv)
    notes: list[str] = []

    # Namespace override from actual main-source imports (mixed-project defense).
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
        if src_ns != prof["namespace"]:
            notes.append(f"namespace overridden by source imports: "
                         f"{prof['namespace']} -> {src_ns} (javax={javax_hits}, jakarta={jakarta_hits})")
            prof["namespace"] = src_ns

    # JUnit engine override from existing tests; note vintage availability.
    test_eng = _scan_imports(root, "src/test/java",
                             ("import org.junit.jupiter", "import org.junit.Test", "@RunWith"))
    build_text = (_read_text(os.path.join(root, "build.gradle.kts"))
                  + _read_text(os.path.join(root, "build.gradle"))
                  + _read_text(os.path.join(root, "pom.xml")))
    jupiter_tests = test_eng["import org.junit.jupiter"]
    junit4_tests = test_eng["import org.junit.Test"]
    if jupiter_tests or junit4_tests:
        src_engine = "jupiter" if jupiter_tests >= junit4_tests else "junit4"
        if src_engine != prof["junitEngine"]:
            notes.append(f"junitEngine overridden by existing tests: "
                         f"{prof['junitEngine']} -> {src_engine} "
                         f"(jupiter={jupiter_tests}, junit4={junit4_tests})")
            prof["junitEngine"] = src_engine
            prof["gradleTestMode"] = "useJUnit" if src_engine == "junit4" else "useJUnitPlatform"
    if "junit-vintage" in build_text:
        notes.append("junit-vintage-engine present: JUnit4 tests run alongside Jupiter")

    degraded = bv is None
    if degraded:
        notes.append("Spring Boot version not detected from build files; profile assumes "
                     "'latest' (Boot 4.x). Caller should interview (interactive) or warn (CI).")

    return {
        "status": "ok",
        "springProfile": {
            "bootVersion": bv,
            "bootMajor": prof["bootMajor"],
            "namespace": prof["namespace"],
            "junitEngine": prof["junitEngine"],
            "mockAnnotation": prof["mockAnnotation"],
            "mockImport": prof["mockImport"],
            "javaBaseline": prof["javaBaseline"],
            "gradleTestMode": prof["gradleTestMode"],
            "degraded": degraded,
        },
        "versionSource": bv_source,
        "notes": notes,
    }


@mcp.tool()
def list_test_tasks(root: str = ".") -> dict:
    """List the test task / goal entrypoints available for the detected build tool."""
    root = os.path.abspath(root)
    det = _detect(root)
    if det.get("status") != "ok":
        return det

    tool = det["buildTool"]
    if tool == "gradle":
        tasks = [
            {"task": "test", "desc": "Run JUnit Platform unit/slice tests"},
            {"task": "jacocoTestReport", "desc": "Generate JaCoCo XML/HTML coverage report"},
            {"task": "jacocoTestCoverageVerification", "desc": "Enforce coverage gate"},
            {"task": "pitest", "desc": "Run PITest mutation testing"},
            {"task": "integrationTest", "desc": "Run integration tests (if configured)"},
        ]
    else:  # maven
        tasks = [
            {"task": "test", "desc": "Run Surefire unit/slice tests"},
            {"task": "verify", "desc": "Run Failsafe integration tests + checks"},
            {"task": "jacoco:report", "desc": "Generate JaCoCo XML/HTML coverage report"},
            {"task": "jacoco:check", "desc": "Enforce coverage gate"},
            {"task": "org.pitest:pitest-maven:mutationCoverage", "desc": "Run PITest mutation testing"},
        ]

    return {"status": "ok", "buildTool": tool, "wrapper": det["wrapper"], "tasks": tasks}


@mcp.tool()
def run_targeted_tests(build_tool: str, test_pattern: str, root: str = ".",
                       with_coverage: bool = True) -> dict:
    """Run the NARROWEST test scope for a given pattern; return a TestRunResult.

    Gradle : ./gradlew test --tests <pat> [jacocoTestReport] [--offline]
    Maven  : mvn -B test -Dtest=<pat> [jacoco:report] [-o]

    All arguments are shlex-quoted. Network is OFF by default unless
    BUILD_TEST_ALLOW_NETWORK is set.
    """
    root = os.path.abspath(root)
    build_tool = (build_tool or "").strip().lower()
    if build_tool not in ("gradle", "maven"):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"unsupported build_tool: {build_tool!r}"}

    if not os.path.isdir(root):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"directory not found: {root}"}

    offline = not _network_allowed()
    pattern_q = shlex.quote(test_pattern)

    if build_tool == "gradle":
        wrapper = os.path.join(root, "gradlew")
        launcher = wrapper if os.path.isfile(wrapper) else "gradle"
        cmd = [launcher, "test", "--tests", test_pattern]
        if with_coverage:
            cmd.append("jacocoTestReport")
        if offline:
            cmd.append("--offline")
    else:  # maven
        wrapper = os.path.join(root, "mvnw")
        launcher = wrapper if os.path.isfile(wrapper) else "mvn"
        cmd = [launcher, "-B", "test", f"-Dtest={test_pattern}"]
        if with_coverage:
            cmd.append("jacoco:report")
        if offline:
            cmd.append("-o")

    # Human-readable command string with shlex quoting for transparency/logging.
    display_cmd = " ".join(shlex.quote(part) for part in cmd)

    exec_meta = _run_subprocess(cmd, cwd=root)

    # Parse JUnit XML regardless of exit code (compile failures still informative).
    xml_paths = _find_junit_xml(root)
    total_passed = 0
    all_failures: list[dict] = []
    for xp in xml_paths:
        p, f = _parse_junit_file(xp)
        total_passed += p
        all_failures.extend(f)

    report_dirs = sorted({os.path.dirname(p) for p in xml_paths})

    if exec_meta["timedOut"]:
        status = "failed"
    elif not xml_paths and exec_meta["exitCode"] != 0:
        status = "failed"
    elif all_failures:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "buildTool": build_tool,
        "command": display_cmd,
        "testPattern": test_pattern,
        "patternQuoted": pattern_q,
        "withCoverage": with_coverage,
        "networkOffline": offline,
        "exitCode": exec_meta["exitCode"],
        "timedOut": exec_meta["timedOut"],
        "passed": total_passed,
        "failed": all_failures,
        "reportPaths": report_dirs,
        "stdoutTail": exec_meta["stdoutTail"],
        "stderrTail": exec_meta["stderrTail"],
    }


@mcp.tool()
def parse_junit_xml(root: str = ".") -> dict:
    """Parse Gradle/Maven JUnit XML reports -> passed + classified failures[].

    Gradle: build/test-results/test/*.xml ; Maven: target/surefire-reports/*.xml.
    Each failure is classified TEST_COMPILE_FAILED / TEST_RUNTIME_FAILED / FLAKY_SUSPECTED.
    """
    root = os.path.abspath(root)
    xml_paths = _find_junit_xml(root)

    total_passed = 0
    all_failures: list[dict] = []
    for xp in xml_paths:
        p, f = _parse_junit_file(xp)
        total_passed += p
        all_failures.extend(f)

    report_dirs = sorted({os.path.dirname(p) for p in xml_paths})

    if not xml_paths:
        status = "failed"
    elif all_failures:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "passed": total_passed,
        "failed": all_failures,
        "reportPaths": report_dirs,
    }


@mcp.tool()
def parse_jacoco_report(root: str = ".") -> dict:
    """Parse a JaCoCo XML report into per-counter coverage + per-class + uncovered[].

    Gradle: build/reports/jacoco/test/jacocoTestReport.xml ;
    Maven : target/site/jacoco/jacoco.xml.
    Counters: LINE, BRANCH, METHOD, CLASS, INSTRUCTION (overall and per class).
    `uncovered[]` lists classes/methods below target so a coverage-closer can act.
    """
    root = os.path.abspath(root)
    jacoco_path = _find_jacoco_xml(root)
    if jacoco_path is None:
        return {"status": "failed", "error": "JACOCO_REPORT_NOT_FOUND",
                "message": f"no jacoco.xml found under: {root}"}
    return _parse_jacoco(jacoco_path)


@mcp.tool()
def parse_pitest_report(root: str = ".") -> dict:
    """Parse a PITest mutations.xml report -> mutationScore + survivedMutants[].

    Gradle: build/reports/pitest/mutations.xml ; Maven: target/pit-reports/mutations.xml.
    Surviving mutants (SURVIVED/NO_COVERAGE) include class/method/line/mutator/status
    so a mutation-analyst can target them.
    """
    root = os.path.abspath(root)
    pitest_path = _find_pitest_xml(root)
    if pitest_path is None:
        return {"status": "failed", "error": "PITEST_REPORT_NOT_FOUND",
                "message": f"no mutations.xml found under: {root}"}
    return _parse_pitest(pitest_path)


@mcp.tool()
def coverage_gate(root: str = ".", line: float = DEFAULT_LINE, branch: float = DEFAULT_BRANCH,
                  method: float = DEFAULT_METHOD, klass: float = DEFAULT_CLASS,
                  mutation: float = DEFAULT_MUTATION) -> dict:
    """Combine JaCoCo + PITest parse and return pass/fail per counter + gaps.

    Returns overall pass flag plus a per-counter breakdown with the actual ratio,
    the required threshold, and pass/fail. Includes uncovered classes and surviving
    mutants as actionable gaps.
    """
    root = os.path.abspath(root)

    jacoco_path = _find_jacoco_xml(root)
    pitest_path = _find_pitest_xml(root)

    counters_result: dict[str, dict] = {}
    gaps: dict = {"uncovered": [], "survivedMutants": []}
    missing: list[str] = []

    if jacoco_path is None:
        missing.append("JACOCO_REPORT_NOT_FOUND")
    else:
        jr = _parse_jacoco(jacoco_path)
        if jr.get("status") != "ok":
            missing.append(jr.get("error", "JACOCO_PARSE_FAILED"))
        else:
            overall = jr["overall"]
            wanted = {"LINE": line, "BRANCH": branch, "METHOD": method, "CLASS": klass}
            for ctype, threshold in wanted.items():
                actual = overall.get(ctype, {}).get("ratio")
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

    if pitest_path is None:
        missing.append("PITEST_REPORT_NOT_FOUND")
    else:
        pr = _parse_pitest(pitest_path)
        if pr.get("status") != "ok":
            missing.append(pr.get("error", "PITEST_PARSE_FAILED"))
        else:
            actual = pr["mutationScore"]
            counters_result["MUTATION"] = {
                "actual": actual, "threshold": mutation,
                "pass": actual >= mutation,
            }
            gaps["survivedMutants"] = pr["survivedMutants"]

    all_pass = bool(counters_result) and all(c["pass"] for c in counters_result.values())

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
        "pitestPath": pitest_path,
    }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("build://metadata")
def build_metadata() -> str:
    """Build-tool metadata for the current working directory (JSON)."""
    return json.dumps(_detect(os.getcwd()), indent=2)


@mcp.resource("build://test-reports")
def test_reports() -> str:
    """Discovered test/coverage/mutation report paths for the CWD (JSON)."""
    root = os.getcwd()
    return json.dumps({
        "junitXml": _find_junit_xml(root),
        "jacocoXml": _find_jacoco_xml(root),
        "pitestXml": _find_pitest_xml(root),
    }, indent=2)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def suggest_test_command(build_tool: str = "auto", test_pattern: str = "") -> str:
    """Suggest the narrowest, network-off test command for the given build tool/pattern."""
    pat = test_pattern or "<FullyQualifiedTestClass>"
    if build_tool == "maven":
        cmd = f"mvn -B -o test -Dtest={shlex.quote(pat)} jacoco:report"
    elif build_tool == "gradle":
        cmd = f"./gradlew --offline test --tests {shlex.quote(pat)} jacocoTestReport"
    else:
        cmd = ("Detect the build tool first (detect_build_tool). "
               "Then for gradle: `./gradlew --offline test --tests <pat> jacocoTestReport`; "
               "for maven: `mvn -B -o test -Dtest=<pat> jacoco:report`.")
    return (
        "Run the NARROWEST possible test scope with the network OFF.\n"
        f"Suggested command: {cmd}\n"
        "Then parse JUnit XML (parse_junit_xml), coverage (parse_jacoco_report), "
        "and mutation (parse_pitest_report), and evaluate with coverage_gate."
    )


def main() -> None:
    """Entry point: run the build-test server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
