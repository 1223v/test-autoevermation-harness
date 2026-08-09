"""Regression guard: PITest-based mutation testing stays removed (v0.25.0).

This file is NOT leftover from a deleted feature — it was created BY the commit that
deleted it (268b469, "Remove mutation testing from harness"). Its job is to fail loudly
if mutation testing ever creeps back into the tool surface, the build/CI examples, or
the report-discovery paths. The repo uses this pattern elsewhere: see
`RegexFallbackRemovalTests` in test_update_persistence.py, which guards the v0.31.0
regex-fallback removal the same way.

Why the stale-report cases still matter. v0.25.0 deliberately did NOT touch the target
project's own build files or CI, because a user's `info.solidsoft.pitest` / `pitest-maven`
configuration is their asset. So a real user can still have a leftover PIT report sitting
on disk at `build/reports/pitest/mutations.xml` — PIT's actual Gradle output path
(pitest.org). These tests prove the harness treats that file as absent rather than
mistaking it for live evidence and advancing the pipeline on it.

Scope note (v0.33.0): five `detect_pipeline_state` entry-stage tests that had accreted
here in v0.25.1 — because these JUnit/JaCoCo fixtures were handy — moved to
test_pipeline_state_contract.py. They were unrelated to mutation and made this file's
name misleading.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "mcp" / "build_test_server.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_test = _load_module("mutation_removal_build_test_server", SERVER_PATH)


def _write_jacoco_report(root: Path, *, missed: int = 0, covered: int = 100) -> Path:
    report = root / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"""<report name="test">
  <counter type="LINE" missed="{missed}" covered="{covered}"/>
  <counter type="BRANCH" missed="{missed}" covered="{covered}"/>
  <counter type="METHOD" missed="{missed}" covered="{covered}"/>
  <counter type="CLASS" missed="{missed}" covered="{covered}"/>
</report>""",
        encoding="utf-8",
    )
    return report


def _write_stale_report(root: Path) -> Path:
    """A leftover PIT report at PIT's real Gradle output path (pitest.org)."""
    report = root / "build" / "reports" / "pitest" / "mutations.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        """<mutations>
  <mutation status="SURVIVED">
    <mutatedClass>com.example.OrderService</mutatedClass>
    <mutatedMethod>place</mutatedMethod>
    <lineNumber>10</lineNumber>
  </mutation>
</mutations>""",
        encoding="utf-8",
    )
    return report


class PublicApiTests(unittest.TestCase):
    def test_fastmcp_exposes_exactly_eleven_non_pit_tools(self) -> None:
        tools = asyncio.run(build_test.mcp.list_tools())
        names = [tool.name for tool in tools]

        self.assertEqual(
            [
                "health",
                "detect_build_tool",
                "detect_spring_profile",
                "list_test_tasks",
                "run_targeted_tests",
                "parse_junit_xml",
                "parse_jacoco_report",
                "detect_pipeline_state",
                "coverage_gate",
                "detect_build_capabilities",
                "check_dependency_cache",
            ],
            names,
        )
        self.assertFalse(hasattr(build_test, "parse_pitest_report"))

    def test_public_signatures_are_coverage_only(self) -> None:
        coverage = inspect.signature(build_test.coverage_gate)
        capabilities = inspect.signature(build_test.detect_build_capabilities)

        self.assertEqual(
            ["root", "line", "branch", "method", "klass"],
            list(coverage.parameters),
        )
        self.assertEqual(["root"], list(capabilities.parameters))

    def test_server_source_has_no_pit_or_mutation_behavior(self) -> None:
        source = SERVER_PATH.read_text(encoding="utf-8").lower()

        self.assertNotIn("pitest", source)
        self.assertNotIn("mutation", source)


class BuildSurfaceTests(unittest.TestCase):
    def test_gradle_maven_and_ci_examples_keep_jacoco_without_mutation_tools(self) -> None:
        paths = (
            PLUGIN_ROOT / "examples" / "gradle" / "build.gradle.kts",
            PLUGIN_ROOT / "examples" / "gradle" / "build-boot2.gradle",
            PLUGIN_ROOT / "examples" / "maven" / "pom-snippet.xml",
            PLUGIN_ROOT / "examples" / "maven" / "pom-snippet-boot2.xml",
            PLUGIN_ROOT / "examples" / "ci" / "gradle-ci.yml",
            PLUGIN_ROOT / "examples" / "ci" / "maven-ci.yml",
        )
        for path in paths:
            with self.subTest(path=path.relative_to(PLUGIN_ROOT)):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("jacoco", text)
                self.assertNotIn("pitest", text)
                self.assertNotIn("run_pitest", text)
                self.assertNotIn("mutations.xml", text)
                self.assertNotIn("mutation", text)

    def test_task_lists_do_not_advertise_pit(self) -> None:
        fixtures = {
            "build.gradle.kts": 'plugins { id("java") }',
            "pom.xml": "<project/>",
        }
        for filename, content in fixtures.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, filename).write_text(content, encoding="utf-8")
                result = build_test.list_test_tasks(tmp)
                rendered = json.dumps(result, ensure_ascii=False).lower()

                self.assertEqual("ok", result["status"])
                self.assertNotIn("pitest", rendered)
                self.assertNotIn("mutation", rendered)

    def test_capabilities_report_only_jacoco_for_gradle_and_maven(self) -> None:
        fixtures = {
            "build.gradle.kts": """
plugins { id("java"); id("jacoco") }
tasks.jacocoTestReport { reports { xml.required.set(true) } }
""",
            "pom.xml": """
<project><build><plugins><plugin>
  <groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId>
  <executions><execution><goals><goal>report</goal></goals></execution></executions>
</plugin></plugins></build></project>
""",
        }
        for filename, content in fixtures.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, filename).write_text(content, encoding="utf-8")
                result = build_test.detect_build_capabilities(tmp)

                self.assertEqual("ok", result["status"])
                self.assertEqual({"jacoco": True, "jacocoXml": True}, result["capabilities"])
                self.assertEqual([], result["missing"])
                self.assertNotIn("junitEngine", result)

    def test_report_discovery_ignores_stale_mutations_xml(self) -> None:
        """Report discovery must not mistake a leftover mutations XML for a real report.

        v0.33.0: this used to go through the `build://test-reports` MCP resource, which
        was deleted as unreachable boilerplate. The regression it guards lives in the
        discovery helpers themselves, so it now calls them directly — same coverage,
        one fewer duplicate surface.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco_report(root)
            _write_stale_report(root)

            reports = {
                "junitXml": build_test._find_junit_xml(tmp),
                "jacocoXml": build_test._find_jacoco_xml(tmp),
            }

        self.assertEqual({"junitXml", "jacocoXml"}, set(reports))
        self.assertIsNotNone(reports["jacocoXml"])


class StaleReportTests(unittest.TestCase):
    def test_coverage_gate_uses_only_jacoco_when_stale_report_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco_report(root)
            _write_stale_report(root)

            result = build_test.coverage_gate(tmp)

        self.assertEqual("ok", result["status"])
        self.assertTrue(result["pass"])
        self.assertEqual({"LINE", "BRANCH", "METHOD", "CLASS"}, set(result["counters"]))
        self.assertEqual({"uncovered"}, set(result["gaps"]))
        self.assertNotIn("pitestPath", result)

    def test_pipeline_state_does_not_advance_from_stale_mutations_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_file = root / "src" / "test" / "java" / "OrderServiceTest.java"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("class OrderServiceTest {}", encoding="utf-8")
            index = root / "test_docs" / "INDEX.md"
            index.parent.mkdir(parents=True)
            index.write_text("# Harness tests", encoding="utf-8")
            _write_jacoco_report(root)
            _write_stale_report(root)

            result = build_test.detect_pipeline_state(tmp)

        self.assertEqual("8", result["highestCompletedStage"])
        self.assertEqual(6, result["recommendedEntryStage"])
        self.assertNotIn("pitestReport", result)
        self.assertNotIn("pitestPath", result["evidence"])


if __name__ == "__main__":
    unittest.main()
