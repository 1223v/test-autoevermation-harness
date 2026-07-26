"""Result-verification upgrade contract tests (v0.27.0).

Covers the four approved improvements:
  1. parse_junit_xml exposes per-method machine records (testcases[]/skipped)
     so a method-level verdict is proven, never inferred from failed[] absence.
  2. Retry-history elements (Surefire rerunFailure, Gradle mergeReruns
     flakyFailure) surface as flaky instead of silently passing.
  3. repo-ast exposes receiver-aware call records (methodCallDetails) so the
     conformance gate can reject same-named calls on the wrong collaborator.
  4. The conformance contract records judgment (machine vs read-based) and the
     NOT_EXECUTED nonconformance class across all consumer specs.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "mcp" / "build_test_server.py"
AST_SERVER_PATH = PLUGIN_ROOT / "mcp" / "repo_ast_server.py"
ASTCLI_JAR = PLUGIN_ROOT / "mcp" / "javaparser-cli" / "target" / "astcli-1.0.0-shaded.jar"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_test = _load_module("rvu_build_test_server", SERVER_PATH)
repo_ast = _load_module("rvu_repo_ast_server", AST_SERVER_PATH)


_JUNIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.example.OrderServiceTest" tests="4" failures="1" skipped="1">
  <testcase classname="com.example.OrderServiceTest" name="sc001_pass"/>
  <testcase classname="com.example.OrderServiceTest" name="sc002_fail">
    <failure type="org.opentest4j.AssertionFailedError" message="expected X"/>
  </testcase>
  <testcase classname="com.example.OrderServiceTest" name="sc003_disabled">
    <skipped/>
  </testcase>
  <testcase classname="com.example.OrderServiceTest" name="sc004_flaky_pass">
    <flakyFailure type="java.net.SocketTimeoutException" message="timed out"/>
  </testcase>
</testsuite>
"""


class JunitPerMethodRecordTests(unittest.TestCase):
    """#1/#2 — per-method machine record + flaky surfacing."""

    def _write_report(self, root: Path, body: str = _JUNIT_XML) -> Path:
        report_dir = root / "build" / "test-results" / "test"
        report_dir.mkdir(parents=True)
        path = report_dir / "TEST-com.example.OrderServiceTest.xml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_parse_junit_file_returns_testcases_with_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_report(Path(tmp))
            passed, failures, testcases = build_test._parse_junit_file(str(path))

        self.assertEqual(2, passed)  # sc001 + sc004 (flaky but eventually green)
        self.assertEqual(1, len(failures))
        self.assertEqual({"sc001_pass": "passed",
                          "sc002_fail": "failed",
                          "sc003_disabled": "skipped",
                          "sc004_flaky_pass": "passed"},
                         {t["name"]: t["result"] for t in testcases})

    def test_skipped_testcase_is_neither_passed_nor_failed_but_identified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_report(Path(tmp))
            passed, failures, testcases = build_test._parse_junit_file(str(path))

        failed_ids = {f["test"] for f in failures}
        self.assertNotIn("com.example.OrderServiceTest.sc003_disabled", failed_ids)
        skipped = [t for t in testcases if t["result"] == "skipped"]
        self.assertEqual(["sc003_disabled"], [t["name"] for t in skipped])

    def test_flaky_retry_history_is_flagged_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_report(Path(tmp))
            _, _, testcases = build_test._parse_junit_file(str(path))

        flags = {t["name"]: t["flaky"] for t in testcases}
        self.assertTrue(flags["sc004_flaky_pass"])
        self.assertFalse(flags["sc001_pass"])

    def test_surefire_rerun_elements_also_count_as_flaky(self) -> None:
        body = _JUNIT_XML.replace("flakyFailure", "rerunFailure")
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_report(Path(tmp), body)
            _, _, testcases = build_test._parse_junit_file(str(path))
        flags = {t["name"]: t["flaky"] for t in testcases}
        self.assertTrue(flags["sc004_flaky_pass"])

    def test_parse_junit_xml_tool_exposes_machine_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write_report(Path(tmp))
            result = build_test.parse_junit_xml(tmp)

        self.assertEqual("partial", result["status"])
        self.assertEqual(2, result["passed"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(4, len(result["testcases"]))
        self.assertEqual(["com.example.OrderServiceTest.sc004_flaky_pass"],
                         result["flaky"])

    def test_missing_reports_keep_failed_status_with_empty_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_test.parse_junit_xml(tmp)
        self.assertEqual("failed", result["status"])
        self.assertEqual([], result["testcases"])
        self.assertEqual(0, result["skipped"])
        self.assertEqual([], result["flaky"])


class MethodCallDetailTests(unittest.TestCase):
    """#3 — receiver-aware call records."""

    def test_method_call_details_normalizes_cli_records(self) -> None:
        cls = {
            "methods": [
                {
                    "name": "sc001_cancel",
                    "invokedMethods": ["cancel", "assertThat"],
                    "invokedCalls": [
                        {"name": "cancel", "scope": "orderService"},
                        {"name": "assertThat", "scope": ""},
                        {"name": "", "scope": "junk"},   # dropped: no name
                        "not-a-dict",                     # dropped: wrong shape
                    ],
                }
            ]
        }
        details = repo_ast._method_call_details(cls)
        self.assertEqual(
            {"sc001_cancel": [
                {"name": "cancel", "scope": "orderService"},
                {"name": "assertThat", "scope": ""},
            ]},
            details,
        )

    def test_regex_fallback_yields_empty_call_details(self) -> None:
        cls = {"methods": [{"name": "sc001", "invokedMethods": [], "invokedCalls": []}]}
        self.assertEqual({"sc001": []}, repo_ast._method_call_details(cls))

    @unittest.skipUnless(
        ASTCLI_JAR.is_file() and shutil.which("java"),
        "astcli jar or JDK not available",
    )
    def test_astcli_emits_receiver_scopes(self) -> None:
        import json

        sample = PLUGIN_ROOT / "examples" / "java" / "OrderAmountCalculatorTest.java"
        out = subprocess.run(
            ["java", "-jar", str(ASTCLI_JAR), str(sample)],
            capture_output=True, text=True, timeout=120, check=True,
        )
        data = json.loads(out.stdout)
        methods = data["classes"][0]["methods"]
        calls = [c for m in methods for c in m.get("invokedCalls", [])]
        self.assertTrue(calls, "invokedCalls must be emitted by the CLI")
        self.assertTrue(all(set(c) == {"name", "scope"} for c in calls))
        # A field-receiver call must carry its bare receiver identifier.
        self.assertIn("calculator", {c["scope"] for c in calls})


class ConformanceContractSpecTests(unittest.TestCase):
    """#1/#3/#4 — consumer specs stay in lockstep with the machine-record contract."""

    VERIFIER = (PLUGIN_ROOT / "agents" / "scenario-conformance-verifier.md").read_text(encoding="utf-8")
    VERIFY_SKILL = (PLUGIN_ROOT / "skills" / "verify-scenarios" / "SKILL.md").read_text(encoding="utf-8")
    PIPELINE = (PLUGIN_ROOT / "skills" / "full-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    SCENARIO_DOCS = (PLUGIN_ROOT / "references" / "scenario-docs.md").read_text(encoding="utf-8")
    FIXER = (PLUGIN_ROOT / "agents" / "test-fixer.md").read_text(encoding="utf-8")

    def test_verifier_requires_machine_confirmation_of_execution(self) -> None:
        self.assertIn("testcases[]", self.VERIFIER)
        self.assertIn("NOT_EXECUTED", self.VERIFIER)
        self.assertIn("methodCallDetails", self.VERIFIER)
        self.assertIn('"judgment"', self.VERIFIER)

    def test_not_executed_routes_through_all_consumers(self) -> None:
        for name, text in (
            ("verify-scenarios", self.VERIFY_SKILL),
            ("full-pipeline", self.PIPELINE),
            ("scenario-docs", self.SCENARIO_DOCS),
            ("test-fixer", self.FIXER),
        ):
            self.assertIn("NOT_EXECUTED", text, f"{name} must route NOT_EXECUTED")

    def test_judgment_field_is_specified_in_ssot_and_skill_prompts(self) -> None:
        for name, text in (
            ("verify-scenarios", self.VERIFY_SKILL),
            ("full-pipeline", self.PIPELINE),
            ("scenario-docs", self.SCENARIO_DOCS),
        ):
            self.assertIn("judgment", text, f"{name} must specify judgment")

    def test_receiver_check_is_specified_in_prompts(self) -> None:
        self.assertIn("methodCallDetails", self.VERIFY_SKILL)
        self.assertIn("methodCallDetails", self.PIPELINE)
        self.assertIn("methodCallDetails", self.SCENARIO_DOCS)


if __name__ == "__main__":
    unittest.main()
