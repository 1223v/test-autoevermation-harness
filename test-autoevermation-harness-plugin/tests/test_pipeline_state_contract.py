"""detect_pipeline_state entry-stage contract (durable resume).

Guards how `detect_pipeline_state` maps durable on-disk evidence (generated tests,
JUnit XML, JaCoCo XML) onto `highestCompletedStage` / `recommendedEntryStage`. The
invariant these protect is that resume must never SKIP a stage it cannot prove was
completed for the current source — a green-looking report is not by itself a licence
to re-enter a later stage.

v0.33.0: split out of `test_mutation_removal.py`. These tests were parked there in
v0.25.1 only because the JUnit/JaCoCo fixtures already lived in that file; they have
nothing to do with the v0.25.0 mutation-testing removal. Keeping them under a
mutation-themed filename made the suite's intent unreadable.

Self-contained by repo convention: every tests/*.py loads the server module by path
and carries its own fixtures (see test_env_and_staleness.py, which likewise keeps a
local `_write_jacoco`). There is no __init__.py and no shared helper module.
"""

from __future__ import annotations

import importlib.util
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


build_test = _load_module("pipeline_state_build_test_server", SERVER_PATH)


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


def _write_junit_report(root: Path, *, failed: bool = False) -> Path:
    report = root / "build" / "test-results" / "test" / "TEST-OrderServiceTest.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    failure = '<failure type="AssertionError">expected true</failure>' if failed else ""
    report.write_text(
        f"""<testsuite name="OrderServiceTest" tests="1" failures="{int(failed)}">
  <testcase classname="OrderServiceTest" name="placesOrder">{failure}</testcase>
</testsuite>""",
        encoding="utf-8",
    )
    return report


def _write_empty_junit_report(root: Path) -> Path:
    report = root / "build" / "test-results" / "test" / "TEST-Empty.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        '<testsuite name="Empty" tests="0" failures="0"></testsuite>',
        encoding="utf-8",
    )
    return report


def _seed_project(root: Path) -> None:
    """Minimum evidence that the harness ran here: a generated test + test_docs index.

    detect_pipeline_state requires harness provenance before it will report any
    completed stage, so every case below needs this baseline.
    """
    test_file = root / "src" / "test" / "java" / "OrderServiceTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("class OrderServiceTest {}", encoding="utf-8")
    index = root / "test_docs" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text("# Harness tests", encoding="utf-8")


class PipelineStateEntryStageTests(unittest.TestCase):
    def test_pipeline_state_maps_durable_evidence_to_new_entry_stages(self) -> None:
        cases = (
            (False, False, "5", 6),
            (False, True, "8", 6),
            (True, False, "6", 8),
            (True, True, "8", 9),
        )
        for has_junit, has_jacoco, highest, entry in cases:
            with self.subTest(junit=has_junit, jacoco=has_jacoco):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _seed_project(root)
                    if has_junit:
                        _write_junit_report(root)
                    if has_jacoco:
                        _write_jacoco_report(root)

                    result = build_test.detect_pipeline_state(tmp)

                self.assertEqual(highest, result["highestCompletedStage"])
                self.assertEqual(entry, result["recommendedEntryStage"])

    def test_low_coverage_jacoco_reenters_stage_8_instead_of_skipping_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_project(root)
            _write_junit_report(root)
            _write_jacoco_report(root, missed=99, covered=1)

            state = build_test.detect_pipeline_state(tmp)
            gate = build_test.coverage_gate(tmp)

        self.assertEqual("8", state["highestCompletedStage"])
        self.assertFalse(state["jacocoReport"]["gatePassed"])
        self.assertEqual(8, state["recommendedEntryStage"])
        self.assertFalse(gate["pass"])

    def test_unknown_thresholds_are_conservative_until_explicitly_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_project(root)
            _write_junit_report(root)
            _write_jacoco_report(root, missed=4, covered=96)

            conservative = build_test.detect_pipeline_state(tmp)
            configured = build_test.detect_pipeline_state(
                tmp, line=0.95, branch=0.95, method=0.95, klass=0.95
            )

        self.assertEqual(8, conservative["recommendedEntryStage"])
        self.assertEqual(9, configured["recommendedEntryStage"])

    def test_failed_junit_report_reenters_stage_6_even_with_full_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_project(root)
            _write_junit_report(root, failed=True)
            _write_jacoco_report(root)

            state = build_test.detect_pipeline_state(tmp)

        self.assertEqual("8", state["highestCompletedStage"])
        self.assertEqual(1, state["junitReport"]["failed"])
        self.assertEqual(6, state["recommendedEntryStage"])

    def test_zero_test_junit_report_is_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_project(root)
            _write_empty_junit_report(root)
            _write_jacoco_report(root)

            state = build_test.detect_pipeline_state(tmp)

        self.assertEqual(0, state["junitReport"]["passed"])
        self.assertEqual(6, state["recommendedEntryStage"])


if __name__ == "__main__":
    unittest.main()
