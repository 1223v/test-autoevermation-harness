#!/usr/bin/env python3
"""build_test_server.py — REAL build-test MCP server (coverage/mutation-aware engine).

FastMCP server named "build-test". Coverage/mutation-aware test execution engine for
the Spring test-harness plugin.

Design source of truth:
  - RESEARCH_NOTES.md  (§1 FastMCP API, §3 JaCoCo 0.8.12, §4 PITest, §6 near-100% policy;
                        build-test-mcp design + TestRunResult schema)
  - Build-tool detection and JUnit/JaCoCo/PITest report parsing are implemented inline.

Standard library only (subprocess, xml.etree, json, os, shlex). Python 3.10+.

Security posture (RESEARCH_NOTES §build-test-mcp, §권한과 보안):
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

try:
    from mcp.server.fastmcp import FastMCP
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
    """Network is OFF by default; only ON when BUILD_TEST_ALLOW_NETWORK is truthy."""
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
    ("*", "build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
    ("*", "target", "site", "jacoco", "jacoco.xml"),
)
_PITEST_REL = (
    ("build", "reports", "pitest", "mutations.xml"),
    ("target", "pit-reports", "mutations.xml"),
    ("*", "build", "reports", "pitest", "mutations.xml"),
    ("*", "target", "pit-reports", "mutations.xml"),
)


def _find_reports(root: str, candidates: tuple, recursive_name: str | None = None) -> list[str]:
    """Collect report paths matching any candidate (in order); "*" candidates are globbed,
    plain candidates matched by isfile. If none match and recursive_name is given, fall back
    to a recursive ``**/<recursive_name>`` search. Returns all matches (possibly empty)."""
    found: list[str] = []
    for rel in candidates:
        pat = os.path.join(root, *rel)
        if "*" in pat:
            found.extend(glob.glob(pat))
        elif os.path.isfile(pat):
            found.append(pat)
    if not found and recursive_name:
        found.extend(glob.glob(os.path.join(root, "**", recursive_name), recursive=True))
    return found


def _find_junit_xml(root: str) -> list[str]:
    """Locate JUnit XML reports for Gradle and Maven (incl. one level of submodules)."""
    return _find_reports(root, _JUNIT_REL)


def _safe_parse_xml(path: str) -> tuple:
    """Parse an XML file; return (root_element, None) or (None, 'XML parse error: ...')."""
    try:
        return ET.parse(path).getroot(), None
    except ET.ParseError as exc:
        return None, f"XML parse error: {exc}"


def _parse_junit_file(path: str) -> tuple[int, list[dict]]:
    """Parse one JUnit XML file -> (passed_count, failures[])."""
    root_el, err = _safe_parse_xml(path)
    if err:
        return 0, [{"test": path, "type": "TEST_RUNTIME_FAILED", "message": err}]

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
    found = _find_reports(root, _JACOCO_REL, "jacoco*.xml")
    return found[0] if found else None


def _counter_ratio(missed: int, covered: int) -> float:
    total = missed + covered
    return (covered / total) if total > 0 else 1.0


def _parse_jacoco(jacoco_path: str) -> dict:
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
    found = _find_reports(root, _PITEST_REL, "mutations.xml")
    return found[0] if found else None


def _parse_pitest(pitest_path: str) -> dict:
    """Parse a PITest mutations.xml -> mutationScore + survivedMutants[]."""
    root_el, err = _safe_parse_xml(pitest_path)  # <mutations>
    if err:
        return {"status": "failed", "error": "PITEST_PARSE_FAILED",
                "message": err, "reportPath": pitest_path}
    total = 0
    killed = 0
    survived_mutants: list[dict] = []

    # status values: KILLED, SURVIVED, NO_COVERAGE, TIMED_OUT, MEMORY_ERROR, RUN_ERROR.
    # PIT counts a mutation as *detected* (killed) whenever a test run against it
    # fails or aborts abnormally — KILLED, TIMED_OUT, MEMORY_ERROR, RUN_ERROR.
    # Only SURVIVED / NO_COVERAGE are undetected. Matching PIT's own definition
    # avoids understating mutationScore and spurious MUTATION-gate failures.
    _surviving_statuses = ("SURVIVED", "NO_COVERAGE")
    _detected_statuses = ("KILLED", "TIMED_OUT", "MEMORY_ERROR", "RUN_ERROR")

    for mut in root_el.findall("mutation"):
        total += 1
        status = (mut.get("status") or "").upper()
        if status in _detected_statuses:
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


def _run_subprocess(cmd: "list[str] | str", cwd: str) -> dict:
    """Run a subprocess and return execution metadata.

    POSIX는 argv 리스트, Windows 배치 래퍼는 사전 조립된 `cmd.exe /s /c "…"` 문자열을
    받는다(Windows에서 문자열은 CreateProcess 커맨드라인으로 그대로 전달됨 — 재인용 없음).
    Offline mode is enforced by the build CLI flags (gradle --offline / maven -o)
    added in run_targeted_tests, not here; this only inherits the current environment.
    """
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
def health() -> dict:
    """Side-effect-free diagnostic probe: report server config status.

    Reports the plugin version and whether outbound network is allowed
    (BUILD_TEST_ALLOW_NETWORK), without running any build. Never raises.
    """
    try:
        network_allowed = _network_allowed()
    except Exception:
        network_allowed = False
    return {
        "server": "build-test",
        "pluginVersion": _plugin_version(),
        "networkAllowed": network_allowed,
    }


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

    requires_confirmation = bool(conflicts)
    if requires_confirmation:
        next_actions.append("PROFILE_CONFLICT: build-file vs source disagree; the agent must "
                            "confirm the correct value via AskUserQuestion (interactive) or stop (CI). "
                            "See references/fallback-policy.md #6.")

    degraded = bv is None
    if degraded:
        notes.append("Spring Boot version not detected from build files.")
        next_actions.append("INTERVIEW_REQUIRED: Spring Boot version undetected. The agent must ask "
                            "the user for the Boot major/profile via AskUserQuestion (interactive) or "
                            "stop (CI). Do NOT assume a profile. See references/fallback-policy.md #4.")

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
        "interviewRequired": degraded,
        "requiresConfirmation": requires_confirmation,
        "conflicts": conflicts,
        "notes": notes,
        "nextActions": next_actions,
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


def _build_test_command(build_tool: str, root: str, test_pattern: str,
                        with_coverage: bool, offline: bool) -> "list[str] | str":
    """Construct the narrowest gradle/maven test command (wrapper-aware, cross-platform).

    Windows: 래퍼는 gradlew.bat/mvnw.cmd이고, PATH의 gradle/mvn도 .bat/.cmd 심(shim)이다.
    배치 파일은 CreateProcess로 직접 spawn할 수 없으므로 cmd.exe 를 경유하되,
    `/c`의 따옴표 제거 규칙(따옴표가 정확히 2개면 바깥쪽을 벗김 — `cmd /?`)이
    공백 경로의 래퍼를 깨뜨리므로 **`/s /c` + tail 전체 재인용** 문자열로 반환한다.
    (Windows에서 subprocess는 문자열을 CreateProcess에 그대로 전달한다.)
    (test_pattern은 run_targeted_tests에서 화이트리스트 검증됨 — cmd.exe 메타문자 유입 차단)
    """
    win = os.name == "nt"
    if build_tool == "gradle":
        wrapper_names = ("gradlew.bat", "gradlew.cmd") if win else ("gradlew",)
        fallback = "gradle"
    else:  # maven
        wrapper_names = ("mvnw.cmd", "mvnw.bat") if win else ("mvnw",)
        fallback = "mvn"
    launcher = fallback
    for name in wrapper_names:
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            launcher = cand
            break

    if build_tool == "gradle":
        cmd = [launcher, "test", "--tests", test_pattern]
        if with_coverage:
            cmd.append("jacocoTestReport")
        if offline:
            cmd.append("--offline")
    else:  # maven
        cmd = [launcher, "-B", "test", f"-Dtest={test_pattern}"]
        if with_coverage:
            cmd.append("jacoco:report")
        if offline:
            cmd.append("-o")

    if win:
        return f'cmd.exe /s /c "{subprocess.list2cmdline(cmd)}"'
    return cmd


def _classify_run_status(timed_out: bool, xml_paths: list, exit_code: int,
                         failures: list) -> str:
    """Map a test run outcome to ok/partial/failed.

    A non-zero build is never "ok" even when the parsed reports show no individual
    test failure (compile error, coverage-verification failure, etc.).
    """
    if timed_out:
        return "failed"
    if not xml_paths and exit_code != 0:
        return "failed"
    if failures:
        return "partial"
    if exit_code != 0:
        return "failed"
    return "ok"


@mcp.tool()
def run_targeted_tests(build_tool: str, test_pattern: str, root: str = ".",
                       with_coverage: bool = True, online: bool = False) -> dict:
    """Run the NARROWEST test scope for a given pattern; return a TestRunResult.

    Gradle : ./gradlew test --tests <pat> [jacocoTestReport] [--offline]
    Maven  : mvn -B test -Dtest=<pat> [jacoco:report] [-o]

    All arguments are shlex-quoted. Network is OFF by default unless
    BUILD_TEST_ALLOW_NETWORK is set.

    `online=True` requests a one-time NETWORK-ON run so a COLD dependency cache (or
    newly added JaCoCo/PITest plugins) can be resolved — Gradle `--offline` fails fast
    when a required module is not cached (Gradle Dependency Caching). The caller (skill)
    decides this after `check_dependency_cache` + user approval (fallback-policy.md #18);
    once primed, subsequent runs go offline again.
    """
    root = os.path.abspath(root)
    build_tool = (build_tool or "").strip().lower()
    if build_tool not in ("gradle", "maven"):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"unsupported build_tool: {build_tool!r}"}

    if not os.path.isdir(root):
        return {"status": "failed", "error": "BUILD_TOOL_UNDETECTED",
                "message": f"directory not found: {root}"}

    # 클래스/메서드 패턴 화이트리스트 — 셸 메타문자 유입 차단.
    # Windows에서는 배치 래퍼 실행이 cmd.exe 를 경유하므로 필수 방어선이다.
    # ! [ ] 는 Surefire 선택자(-Dtest=!SlowIT, Test#method[1])용 — cmd 지연 확장(/v:on)은
    # 이 서버가 켜지 않으므로 ! 는 안전하다.
    if not re.fullmatch(r"[A-Za-z0-9_.$#*,!\[\]]+", test_pattern or ""):
        return {"status": "failed", "error": "INVALID_TEST_PATTERN",
                "message": "test_pattern may contain only letters, digits and . $ # * _ , ! [ ] "
                           f"(class/method patterns); got: {test_pattern!r}"}

    offline = (not _network_allowed()) and (not online)
    pattern_q = shlex.quote(test_pattern)
    cmd = _build_test_command(build_tool, root, test_pattern, with_coverage, offline)

    # Human-readable command string with shlex quoting for transparency/logging.
    # (Windows 배치 경로는 이미 cmd.exe /s /c 문자열로 조립됨 — 그대로 기록)
    display_cmd = cmd if isinstance(cmd, str) else " ".join(shlex.quote(part) for part in cmd)

    # Remove stale JUnit XML before the run so a failed build (e.g. a test/main
    # compile error that produces no fresh reports) can't be reported green from
    # a previous run's leftover reports. Surefire/Gradle do not always clear them.
    for stale in _find_junit_xml(root):
        try:
            os.remove(stale)
        except OSError:
            pass

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

    status = _classify_run_status(exec_meta["timedOut"], xml_paths,
                                  exec_meta["exitCode"], all_failures)

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
def detect_pipeline_state(root: str = ".") -> dict:
    """Reconstruct full-pipeline progress from DURABLE on-disk evidence (not _workspace/).

    `_workspace/` intermediate artifacts are .gitignored and ephemeral, so after a fresh
    clone / git checkout / new session / workspace rotation the pipeline cannot tell that
    tests, approved scenarios, and coverage/mutation reports already exist — full-pipeline
    Phase 0 would then misclassify the project as a first run and restart from stage 0.
    This tool scans the durable, committable evidence and maps it to the highest completed
    pipeline stage so Phase 0 can resume at the right stage.

    Evidence -> stage:
      test_docs/refactoring/RA-*.md        -> stage 3.5 (refactor advisory)
      test_docs/scenarios/*.md (approved)  -> stages 4 / 4.5 (scenarios designed + approved)
      src/test/java/**/*Test(s).java       -> stage 5 (tests generated) — ONLY with provenance
      JUnit XML report                     -> stage 6 (tests run)
      JaCoCo XML report                    -> stage 8 (coverage measured)
      PITest mutations.xml report          -> stage 9 (mutation measured)

    PROVENANCE GATE: a bare *Test*.java proves a test exists, not that THIS harness wrote
    it. Harness-authored tests are evidenced by test_docs/ (scenario docs / INDEX.md). When
    tests exist WITHOUT that provenance they are FOREIGN (hand-written / pre-existing):
    `foreignTestsPresent=true`, `harnessProvenance=false`, they do NOT count as stage 5, and
    `recommendedEntryStage` stays 0 (initial run) so the harness still designs+generates
    tests — the pipeline threads foreign tests as existingTestPaths to augment coverage gaps
    without overwriting them. `resumable` means "a harness pipeline left mid-stream state";
    foreign-tests-only is not resumable.

    Every probe is fail-safe: any error yields a null/empty field (detection must never
    break the pipeline — same posture as guard-gate-artifacts fail-open). Returns
    `highestCompletedStage` + `recommendedEntryStage` so CI has a deterministic default;
    interactive mode may still ask the user which stage to resume from.
    """
    root = os.path.abspath(root)

    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    # --- durable test files (stage 5) ---
    test_files: list[str] = []
    test_base = os.path.join(root, "src", "test", "java")
    if os.path.isdir(test_base):
        for dirpath, _dirs, files in os.walk(test_base):
            for fn in files:
                if fn.endswith(".java") and ("Test" in fn or "Tests" in fn):
                    test_files.append(os.path.join(dirpath, fn))
    has_tests = bool(test_files)

    # --- scenarios (stages 4 / 4.5): count test_docs/scenarios/*.md by `approval:` ---
    scen_dir = os.path.join(root, "test_docs", "scenarios")
    scen_paths = _safe(lambda: glob.glob(os.path.join(scen_dir, "*.md")), []) or []
    approved_scen = pending_scen = excluded_scen = 0
    for sp in scen_paths:
        txt = _safe(lambda p=sp: _read_text(p, limit=8000), "") or ""
        m = re.search(r"(?m)^\s*approval:\s*([A-Za-z]+)", txt)
        state = m.group(1).lower() if m else ""
        if state == "approved":
            approved_scen += 1
        elif state == "excluded":
            excluded_scen += 1
        else:
            pending_scen += 1

    # --- refactor advisories (stage 3.5) ---
    ra_dir = os.path.join(root, "test_docs", "refactoring")
    ra_paths = _safe(lambda: glob.glob(os.path.join(ra_dir, "RA-*.md")), []) or []
    has_index = os.path.isfile(os.path.join(root, "test_docs", "INDEX.md"))

    # --- reports (stages 6 / 8 / 9), reusing existing parsers, fail-safe ---
    junit = _safe(lambda: parse_junit_xml(root), None)
    jacoco = _safe(lambda: parse_jacoco_report(root), None)
    pitest = _safe(lambda: parse_pitest_report(root), None)

    def _report_ok(r):
        return bool(r) and r.get("status") in ("ok", "partial")

    junit_ok = _report_ok(junit)
    jacoco_ok = _report_ok(jacoco)
    pitest_ok = _report_ok(pitest)

    junit_summary = {"present": False}
    if junit_ok:
        junit_summary = {"present": True, "passed": junit.get("passed", 0),
                         "failed": len(junit.get("failed", []))}
    jacoco_summary = {"present": False}
    if jacoco_ok:
        overall = (jacoco.get("overall") or {})
        jacoco_summary = {"present": True,
                          "line": (overall.get("LINE") or {}).get("ratio"),
                          "branch": (overall.get("BRANCH") or {}).get("ratio")}
    pitest_summary = {"present": False}
    if pitest_ok:
        pitest_summary = {"present": True, "mutationScore": pitest.get("mutationScore")}

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
    test_provenance = has_index or bool(scen_paths)
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
    if harness_tests and pitest_ok:
        highest = "9"

    # recommended entry stage (deterministic CI default):
    #  - harness-authored tests exist -> durable resume from 6(run)->8->9->10, no regen.
    #  - scenarios approved but tests missing -> enter at 5(generate).
    #  - foreign-tests-only OR nothing durable -> initial full run (stage 0). When foreign
    #    tests are present, the pipeline threads them as existingTestPaths so generate-tests
    #    augments coverage gaps instead of clobbering the hand-written tests.
    if harness_tests:
        recommended = 6
    elif not has_tests and approved_scen > 0:
        recommended = 5
    else:
        recommended = 0

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
        "pitestReport": pitest_summary,
        "workspaceArtifacts": ws_artifacts,
        "highestCompletedStage": highest,
        "recommendedEntryStage": recommended,
        "evidence": {
            "testDir": test_base if has_tests else None,
            "scenarioDir": scen_dir if scen_paths else None,
            "refactorDir": ra_dir if ra_paths else None,
            "junitReportPaths": (junit.get("reportPaths") if junit_ok else []) or [],
            "jacocoPath": _safe(lambda: _find_jacoco_xml(root), None),
            "pitestPath": _safe(lambda: _find_pitest_xml(root), None),
        },
    }


@mcp.tool()
def coverage_gate(root: str = ".", line: float = DEFAULT_LINE, branch: float = DEFAULT_BRANCH,
                  method: float = DEFAULT_METHOD, klass: float = DEFAULT_CLASS,
                  mutation: float = DEFAULT_MUTATION, require_pitest: bool = False) -> dict:
    """Combine JaCoCo + PITest parse and return pass/fail per counter + gaps.

    Returns overall pass flag plus a per-counter breakdown with the actual ratio,
    the required threshold, and pass/fail. Includes uncovered classes and surviving
    mutants as actionable gaps.

    ``require_pitest`` (default False): PITest is opt-in. With the default, the
    mutation report is ignored even if a stale ``mutations.xml`` exists, so stage 8
    and a mutation-disabled pipeline are based only on JaCoCo. Pass true only after
    an enabled stage 9; then a missing report is an error and an existing report is
    evaluated as the MUTATION counter.

    Note: `klass` (CLASS counter) defaults to 1.0 per the near-100% policy. On a
    narrowly-targeted run whose JaCoCo report scope still includes uncovered sibling
    classes, the overall CLASS ratio can be <1.0 and fail the gate; callers scoping
    to a single class should override `klass` (or scope the report) accordingly.
    """
    root = os.path.abspath(root)

    jacoco_path = _find_jacoco_xml(root)
    pitest_path = _find_pitest_xml(root) if require_pitest else None

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

    if require_pitest and pitest_path is None:
        missing.append("PITEST_REPORT_NOT_FOUND")
    elif require_pitest and pitest_path is not None:
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
# Build-capability provisioning (F1) + dependency-cache priming (F2)
#
# These tools EXPOSE SIGNALS ONLY (no file writes). JaCoCo XML is required for stage 8;
# PITest plugin/JUnit/XML capabilities are required only when the caller opts in with
# require_pitest=True. Per fallback-policy.md #17/#18 the consuming skill detects only
# required gaps, asks for approval (interactive) or stops with remediation (CI), then
# applies the minimal build change itself. Sources: references/build-provisioning.md.
# ---------------------------------------------------------------------------

# JaCoCo XML toggle is OFF by default for the Gradle plugin, so the harness's
# parse_jacoco_report finds no jacoco.xml unless this is set explicitly.
_GRADLE_JACOCO_PLUGIN_RE = re.compile(r"""(?:id\s*\(?\s*['"]jacoco['"]|apply\s+plugin:\s*['"]jacoco['"])""")
_GRADLE_JACOCO_XML_RE = re.compile(r"""xml\s*\.\s*(?:required|enabled)\s*(?:\.\s*set\s*\(\s*)?=?\s*true""")
_GRADLE_PITEST_PLUGIN_RE = re.compile(r"""info\.solidsoft\.pitest""")
_GRADLE_PITEST_JUNIT5_RE = re.compile(r"""junit5PluginVersion|pitest-junit5-plugin""")
_GRADLE_PITEST_XML_RE = re.compile(
    r"""outputFormats\s*(?:(?:\.\s*set)\s*\(|=)?[\s\S]{0,256}?['\"]XML['\"]""",
    re.IGNORECASE,
)
_MAVEN_JACOCO_RE = re.compile(r"""jacoco-maven-plugin""")
_MAVEN_JACOCO_REPORT_GOAL_RE = re.compile(r"""<goal>\s*report\s*</goal>""")
_MAVEN_PITEST_RE = re.compile(r"""pitest-maven""")
_MAVEN_PITEST_JUNIT5_RE = re.compile(r"""pitest-junit5-plugin""")
_MAVEN_PITEST_XML_RE = re.compile(
    r"""<outputFormats\b[^>]*>[\s\S]*?<(?:param|value)>\s*XML\s*</(?:param|value)>[\s\S]*?</outputFormats>""",
    re.IGNORECASE,
)


def _gradle_build_text(root: str) -> tuple[str, str]:
    """Return (build-file text, build-file name) for Gradle (.kts preferred)."""
    for name in ("build.gradle.kts", "build.gradle"):
        text = _read_text(os.path.join(root, name))
        if text:
            return text, name
    return "", ""


def _gradle_capabilities(root: str, jupiter: bool, require_pitest: bool = False) -> tuple:
    """Return required capabilities and changes for a Gradle target build."""
    text, fname = _gradle_build_text(root)
    kts = fname.endswith(".kts")
    fref = fname or "build.gradle[.kts]"
    caps = {
        "jacoco": bool(_GRADLE_JACOCO_PLUGIN_RE.search(text)),
        "jacocoXml": bool(_GRADLE_JACOCO_XML_RE.search(text)),
        "pitest": bool(_GRADLE_PITEST_PLUGIN_RE.search(text)),
        "pitestJunit5": (not jupiter) or bool(_GRADLE_PITEST_JUNIT5_RE.search(text)),
        "pitestXml": bool(
            _GRADLE_PITEST_PLUGIN_RE.search(text)
            and _GRADLE_PITEST_XML_RE.search(text)
        ),
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
                if kts else
                "tasks.named('jacocoTestReport') { reports { xml.required = true } }"
            ),
            "reason": "JaCoCo XML 기본 OFF → parse_jacoco_report가 XML 미발견(HTML만 생성)",
            "source": "https://docs.gradle.org/current/userguide/jacoco_plugin.html",
        })
    if require_pitest and not caps["pitest"]:
        missing.append("PITEST_PLUGIN_MISSING")
        proposed.append({
            "file": fref,
            "anchor": "plugins { }",
            "snippet": (
                'id("info.solidsoft.pitest") version "1.19.0"'
                if kts else
                "id 'info.solidsoft.pitest' version '1.19.0'"
            ),
            "reason": "PITest 플러그인 미적용 → pitest 태스크 없음(Task 'pitest' not found)",
            "source": "https://gradle-pitest-plugin.solidsoft.info/",
        })
    if require_pitest and not caps["pitestJunit5"]:
        missing.append("PITEST_JUNIT5_MISSING")
        proposed.append({
            "file": fref,
            "anchor": "pitest { }",
            "snippet": (
                'pitest { junit5PluginVersion.set("1.0.0") }'
                if kts else
                "pitest { junit5PluginVersion = '1.0.0' }"
            ),
            "reason": "JUnit5(Jupiter) 테스트는 pitest-junit5-plugin 필요",
            "source": "https://github.com/pitest/pitest-junit5-plugin",
        })
    if require_pitest and not caps["pitestXml"]:
        missing.append("PITEST_XML_DISABLED")
        proposed.append({
            "file": fref,
            "anchor": "pitest { }",
            "snippet": (
                'pitest { outputFormats.set(setOf("XML", "HTML")) }'
                if kts else
                "pitest { outputFormats = ['XML', 'HTML'] }"
            ),
            "reason": "PIT 기본 출력은 HTML → parse_pitest_report가 mutations.xml을 읽으려면 XML 출력 필요",
            "source": "https://gradle-pitest-plugin.solidsoft.info/",
        })
    return caps, missing, proposed


def _maven_capabilities(root: str, jupiter: bool, require_pitest: bool = False) -> tuple:
    """Return required capabilities and changes for a Maven target build."""
    pom = _read_text(os.path.join(root, "pom.xml"))
    caps = {
        "jacoco": bool(_MAVEN_JACOCO_RE.search(pom)),
        "jacocoXml": bool(_MAVEN_JACOCO_RE.search(pom) and _MAVEN_JACOCO_REPORT_GOAL_RE.search(pom)),
        "pitest": bool(_MAVEN_PITEST_RE.search(pom)),
        "pitestJunit5": (not jupiter) or bool(_MAVEN_PITEST_JUNIT5_RE.search(pom)),
        "pitestXml": bool(_MAVEN_PITEST_RE.search(pom) and _MAVEN_PITEST_XML_RE.search(pom)),
    }
    missing: list[str] = []
    proposed: list[dict] = []
    if not caps["jacoco"] or not caps["jacocoXml"]:
        missing.append("JACOCO_PLUGIN_MISSING" if not caps["jacoco"] else "JACOCO_REPORT_GOAL_MISSING")
        proposed.append({
            "file": "pom.xml",
            "anchor": "<build><plugins>",
            "snippet": (
                "<plugin><groupId>org.jacoco</groupId>"
                "<artifactId>jacoco-maven-plugin</artifactId><version>0.8.12</version>"
                "<executions>"
                "<execution><id>prepare-agent</id><goals><goal>prepare-agent</goal></goals></execution>"
                "<execution><id>report</id><phase>verify</phase><goals><goal>report</goal></goals></execution>"
                "</executions></plugin>"
            ),
            "reason": "jacoco-maven-plugin prepare-agent+report 미바인딩 → jacoco.xml 미생성",
            "source": "https://www.eclemma.org/jacoco/trunk/doc/maven.html",
        })
    if require_pitest and not caps["pitest"]:
        missing.append("PITEST_PLUGIN_MISSING")
        proposed.append({
            "file": "pom.xml",
            "anchor": "<build><plugins>",
            "snippet": (
                "<plugin><groupId>org.pitest</groupId>"
                "<artifactId>pitest-maven</artifactId><version>1.19.0</version>"
                "</plugin>"
            ),
            "reason": "pitest-maven 미적용 → mutationCoverage 골 없음",
            "source": "https://pitest.org/quickstart/maven/",
        })
    if require_pitest and not caps["pitestJunit5"]:
        missing.append("PITEST_JUNIT5_MISSING")
        proposed.append({
            "file": "pom.xml",
            "anchor": "pitest-maven <dependencies>",
            "snippet": (
                "<dependency><groupId>org.pitest</groupId>"
                "<artifactId>pitest-junit5-plugin</artifactId><version>1.0.0</version>"
                "</dependency>"
            ),
            "reason": "JUnit5(Jupiter) 테스트는 pitest-junit5-plugin 필요",
            "source": "https://github.com/pitest/pitest-junit5-plugin",
        })
    if require_pitest and not caps["pitestXml"]:
        missing.append("PITEST_XML_DISABLED")
        proposed.append({
            "file": "pom.xml",
            "anchor": "pitest-maven <configuration>",
            "snippet": (
                "<outputFormats><value>XML</value><value>HTML</value></outputFormats>"
            ),
            "reason": "PIT 기본 출력은 HTML → parse_pitest_report가 mutations.xml을 읽으려면 XML 출력 필요",
            "source": "https://pitest.org/quickstart/maven/",
        })
    return caps, missing, proposed


@mcp.tool()
def detect_build_capabilities(root: str = ".", junit_engine: str = "jupiter",
                              require_pitest: bool = False) -> dict:
    """Detect required JaCoCo-XML and optional PITest capabilities (signal only).

    The coverage gate (parse_jacoco_report) needs a JaCoCo **XML** report, but the Gradle
    JaCoCo plugin emits HTML only by default (`reports { xml.required = true }` required);
    When ``require_pitest`` is false (the default), PITest gaps are informational and do not
    enter ``missing[]`` or change ``status``. When true, the PITest task, JUnit5 adapter, and
    XML output are required because ``parse_pitest_report`` consumes ``mutations.xml``. This
    tool reads the build file and reports each capability plus a minimal, source-cited
    ``proposedChanges[]`` snippet for required gaps. It does NOT modify any file.

    Returns {status, buildTool, pitestRequired,
    capabilities{jacoco,jacocoXml,pitest,pitestJunit5,pitestXml}, missing[],
    proposedChanges[], remediation}.
    """
    root = os.path.abspath(root)
    det = _detect(root)
    if det.get("status") != "ok":
        return det
    tool = det["buildTool"]
    jupiter = (junit_engine or "jupiter").strip().lower() != "junit4"

    if tool == "gradle":
        caps, missing, proposed = _gradle_capabilities(root, jupiter, require_pitest)
    else:  # maven
        caps, missing, proposed = _maven_capabilities(root, jupiter, require_pitest)

    all_ok = not missing
    remediation = ("" if all_ok else
                   "대화형: AskUserQuestion 승인 후 proposedChanges[]를 빌드 파일에 주입(buildChanges[]에 기록). "
                   "CI: 누락 항목과 위 스니펫을 remediation으로 보고하고 중단(HarnessRequest 사전 제공). "
                   "근거·전체 스니펫: references/build-provisioning.md")
    return {
        "status": "ok" if all_ok else "partial",
        "buildTool": tool,
        "junitEngine": "junit4" if not jupiter else "jupiter",
        "pitestRequired": bool(require_pitest),
        "capabilities": caps,
        "missing": missing,
        "proposedChanges": proposed,
        "remediation": remediation,
    }


@mcp.tool()
def check_dependency_cache(build_tool: str = "", root: str = ".") -> dict:
    """Best-effort signal: is the dependency cache likely PRIMED, or COLD? (F2, signal only).

    Network is OFF by default (`--offline`/`-o`), and Gradle fails fast when a required
    module is not cached. A cold cache (or a build file just given new JaCoCo/optional
    PITest plugins) therefore breaks the first offline run. This heuristic checks the shared
    Gradle/Maven caches; it cannot guarantee per-project completeness, so when COLD it
    recommends a one-time online priming run (run_targeted_tests(online=True)) gated by
    approval (fallback-policy.md #18). It does NOT touch the network or any file.

    Returns {status, buildTool, primed, evidence, primeCommand, recommendation}.
    """
    root = os.path.abspath(root)
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
        "and optional mutation (parse_pitest_report), and evaluate with coverage_gate."
    )


def main() -> None:
    """Entry point: run the build-test server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
