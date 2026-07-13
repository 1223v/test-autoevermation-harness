from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_test = _load_module(
    "optional_pitest_build_test_server",
    PLUGIN_ROOT / "mcp" / "build_test_server.py",
)
gate_guard = _load_module(
    "optional_pitest_gate_guard",
    PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py",
)


GRADLE_JACOCO_ONLY = """
plugins {
    id("java")
    id("jacoco")
}

tasks.jacocoTestReport {
    reports { xml.required.set(true) }
}
"""


GRADLE_WITH_PITEST = GRADLE_JACOCO_ONLY + """
plugins {
    id("info.solidsoft.pitest") version "1.19.0"
}

pitest {
    junit5PluginVersion.set("1.0.0")
}
"""


class BuildCapabilityTests(unittest.TestCase):
    def _detect_gradle(self, build_text: str, *, require_pitest: bool):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "build.gradle.kts").write_text(build_text, encoding="utf-8")
            return build_test.detect_build_capabilities(
                tmp,
                junit_engine="jupiter",
                require_pitest=require_pitest,
            )

    def test_pitest_gaps_are_not_required_when_disabled(self):
        result = self._detect_gradle(GRADLE_JACOCO_ONLY, require_pitest=False)

        self.assertEqual("ok", result["status"])
        self.assertFalse(result["pitestRequired"])
        self.assertEqual([], result["missing"])
        self.assertFalse(result["capabilities"]["pitest"])
        self.assertFalse(result["capabilities"]["pitestXml"])

    def test_enabled_pitest_requires_plugin_junit_adapter_and_xml(self):
        result = self._detect_gradle(GRADLE_JACOCO_ONLY, require_pitest=True)

        self.assertEqual("partial", result["status"])
        self.assertTrue(result["pitestRequired"])
        self.assertIn("PITEST_PLUGIN_MISSING", result["missing"])
        self.assertIn("PITEST_JUNIT5_MISSING", result["missing"])
        self.assertIn("PITEST_XML_DISABLED", result["missing"])

    def test_enabled_pitest_requires_xml_output(self):
        result = self._detect_gradle(GRADLE_WITH_PITEST, require_pitest=True)

        self.assertEqual("partial", result["status"])
        self.assertEqual(["PITEST_XML_DISABLED"], result["missing"])

    def test_enabled_pitest_accepts_gradle_xml_output(self):
        result = self._detect_gradle(
            GRADLE_WITH_PITEST
            + """
pitest {
    outputFormats.set(setOf("XML", "HTML"))
}
""",
            require_pitest=True,
        )

        self.assertEqual("ok", result["status"])
        self.assertEqual([], result["missing"])
        self.assertTrue(result["capabilities"]["pitestXml"])

    def test_enabled_pitest_accepts_maven_xml_output(self):
        pom = """
<project>
  <build><plugins>
    <plugin>
      <groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId>
      <executions><execution><goals><goal>report</goal></goals></execution></executions>
    </plugin>
    <plugin>
      <groupId>org.pitest</groupId><artifactId>pitest-maven</artifactId>
      <dependencies><dependency>
        <groupId>org.pitest</groupId><artifactId>pitest-junit5-plugin</artifactId>
      </dependency></dependencies>
      <configuration>
        <outputFormats><value>XML</value><value>HTML</value></outputFormats>
      </configuration>
    </plugin>
  </plugins></build>
</project>
"""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pom.xml").write_text(pom, encoding="utf-8")
            result = build_test.detect_build_capabilities(
                tmp,
                junit_engine="jupiter",
                require_pitest=True,
            )

        self.assertEqual("ok", result["status"])
        self.assertTrue(result["capabilities"]["pitestXml"])

    def test_maven_proposals_do_not_duplicate_junit_adapter(self):
        pom = """
<project>
  <build><plugins>
    <plugin>
      <groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId>
      <executions><execution><goals><goal>report</goal></goals></execution></executions>
    </plugin>
  </plugins></build>
</project>
"""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pom.xml").write_text(pom, encoding="utf-8")
            result = build_test.detect_build_capabilities(
                tmp,
                junit_engine="jupiter",
                require_pitest=True,
            )

        snippets = "\n".join(change["snippet"] for change in result["proposedChanges"])
        self.assertEqual(1, snippets.count("pitest-junit5-plugin"))
        self.assertEqual(1, snippets.count("<outputFormats>"))


class CoverageGateTests(unittest.TestCase):
    def _write_reports(self, root: str):
        jacoco = Path(root, "build", "reports", "jacoco", "test", "jacocoTestReport.xml")
        jacoco.parent.mkdir(parents=True)
        jacoco.write_text(
            """<report name="test">
  <counter type="LINE" missed="0" covered="100"/>
  <counter type="BRANCH" missed="0" covered="100"/>
  <counter type="METHOD" missed="0" covered="100"/>
  <counter type="CLASS" missed="0" covered="10"/>
</report>""",
            encoding="utf-8",
        )
        pitest = Path(root, "build", "reports", "pitest", "mutations.xml")
        pitest.parent.mkdir(parents=True)
        pitest.write_text(
            """<mutations>
  <mutation status="SURVIVED">
    <mutatedClass>com.example.OrderService</mutatedClass>
    <mutatedMethod>place</mutatedMethod>
    <lineNumber>10</lineNumber>
    <mutator>RETURN_VALS</mutator>
    <description>replaced return value</description>
  </mutation>
</mutations>""",
            encoding="utf-8",
        )

    def test_disabled_pitest_ignores_stale_mutation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_reports(tmp)
            result = build_test.coverage_gate(tmp, require_pitest=False)

        self.assertEqual("ok", result["status"])
        self.assertTrue(result["pass"])
        self.assertNotIn("MUTATION", result["counters"])
        self.assertIsNone(result["pitestPath"])

    def test_enabled_pitest_evaluates_mutation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_reports(tmp)
            result = build_test.coverage_gate(tmp, require_pitest=True)

        self.assertEqual("partial", result["status"])
        self.assertFalse(result["pass"])
        self.assertFalse(result["counters"]["MUTATION"]["pass"])
        self.assertIsNotNone(result["pitestPath"])


class MutationArtifactGuardTests(unittest.TestCase):
    def test_explicitly_disabled_mutation_artifact_is_allowed(self):
        result = gate_guard._check_mutation(
            {
                "status": "skipped",
                "reason": "PITEST_DISABLED",
                "mutationScore": None,
                "thresholdMet": None,
                "iterations": 0,
            }
        )

        self.assertEqual("", result)

    def test_arbitrary_skip_cannot_bypass_mutation_gate(self):
        result = gate_guard._check_mutation(
            {
                "status": "skipped",
                "reason": "TOO_SLOW",
                "thresholdMet": None,
                "iterations": 0,
                "survivingMutants": [],
            }
        )

        self.assertIn("게이트 미수행 산출물", result)

    def test_enabled_config_cannot_claim_disabled_skip(self):
        result = gate_guard._check_mutation(
            {
                "status": "skipped",
                "reason": "PITEST_DISABLED",
                "mutationScore": None,
                "thresholdMet": None,
                "iterations": 0,
            },
            mutation_enabled=True,
        )

        self.assertIn("mutation.enabled=false가 확인되지 않아", result)

    def test_invalid_enabled_type_is_not_treated_as_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "00_config-harness.json").write_text(
                json.dumps({"springProfile": {}, "mutation": {"enabled": "false"}}),
                encoding="utf-8",
            )

            result = gate_guard._configured_mutation_enabled(tmp)

        self.assertIsNone(result)


class PromptContractTests(unittest.TestCase):
    def test_config_and_pipeline_expose_optional_mutation_contract(self):
        configure = (PLUGIN_ROOT / "skills" / "configure-harness" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        pipeline = (PLUGIN_ROOT / "skills" / "full-pipeline" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn('"enabled": false', configure)
        self.assertIn("사용 안 함", configure)
        self.assertIn("mutation.enabled", pipeline)
        self.assertIn("PITEST_DISABLED", pipeline)

    def test_build_and_ci_examples_make_pitest_xml_opt_in(self):
        example_paths = (
            PLUGIN_ROOT / "examples" / "gradle" / "build.gradle.kts",
            PLUGIN_ROOT / "examples" / "gradle" / "build-boot2.gradle",
            PLUGIN_ROOT / "examples" / "maven" / "pom-snippet.xml",
            PLUGIN_ROOT / "examples" / "maven" / "pom-snippet-boot2.xml",
        )
        for path in example_paths:
            with self.subTest(path=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("outputFormats", content)
                self.assertIn("XML", content)

        for name in ("gradle-ci.yml", "maven-ci.yml"):
            content = (PLUGIN_ROOT / "examples" / "ci" / name).read_text(encoding="utf-8")
            self.assertIn("vars.RUN_PITEST == 'true'", content)

    def test_maven_example_fragments_are_well_formed(self):
        for name in ("pom-snippet.xml", "pom-snippet-boot2.xml"):
            content = (PLUGIN_ROOT / "examples" / "maven" / name).read_text(
                encoding="utf-8"
            )
            with self.subTest(name=name):
                ET.fromstring(f"<root>{content}</root>")


if __name__ == "__main__":
    unittest.main()
