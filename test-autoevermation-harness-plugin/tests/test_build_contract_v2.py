"""Regression tests for official Gradle/Maven selection and coverage scope contracts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_contract_v2', ROOT / 'mcp/build_test_server.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def junit(root, task='test', skipped=False):
    p = Path(root) / 'build/test-results' / task / 'TEST-Example.xml'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('<testsuite><testcase classname="Example" name="검증">' +
                 ('<skipped/>' if skipped else '') + '</testcase></testsuite>')
    return p


def jacoco(root):
    def counters(miss, covered):
        return ''.join(f'<counter type="{c}" missed="{miss}" covered="{covered}"/>'
                       for c in ('LINE', 'BRANCH', 'METHOD', 'CLASS'))
    p = Path(root) / 'target/site/jacoco/jacoco.xml'
    p.parent.mkdir(parents=True)
    p.write_text('<report><package name="app"><class name="app/Service">' +
                 counters(0, 2) + '</class></package><package name="app/dto">' +
                 '<class name="app/dto/Dto">' + counters(2, 0) +
                 '</class></package>' + counters(2, 2) + '</report>')
    return p


class BuildContractV2(unittest.TestCase):
    def test_gradle_multiple_methods_and_integration_task(self):
        with tempfile.TemporaryDirectory() as root:
            cmd = build._build_test_command('gradle', root, '', False, True,
                    task='integrationTest', test_patterns=['A#검증', 'B#second'])
        self.assertIn('integrationTest', cmd)
        self.assertEqual(2, cmd.count('--tests'))
        self.assertIn('A.검증', cmd)
        self.assertIn('B.second', cmd)

    def test_maven_failsafe_selector(self):
        cmd = build._build_test_command('maven', '.', 'ExampleIT#검증', False, True, task='verify')
        self.assertIn('verify', cmd)
        self.assertIn('-Dit.test=ExampleIT#검증', cmd)
        self.assertNotIn('-Dtest=ExampleIT#검증', cmd)

    def test_conflicting_inputs_and_shell_characters_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as root, patch.object(build, '_run_subprocess') as run:
            result = build.run_targeted_tests('gradle', 'A', root, test_patterns=['B'])
            self.assertEqual('INVALID_TEST_PATTERN', result['error'])
            for value in ('A;touch pwn', 'A%PATH%', 'A&echo', 'A\nB'):
                self.assertEqual('failed', build.run_targeted_tests('gradle', value, root)['status'])
            run.assert_not_called()

    def test_no_xml_is_not_success(self):
        self.assertNotEqual('ok', build._classify_run_status(False, [], 0, []))

    def test_all_skipped_is_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            junit(root, skipped=True)
            result = build.parse_junit_xml(root)
        self.assertNotEqual('ok', result['status'])
        self.assertEqual(0, result['passed'])

    def test_report_files_are_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            expected = junit(root)
            result = build.parse_junit_xml(root)
            self.assertEqual([str(expected)], result['reportPaths'])
            self.assertTrue(Path(result['reportPaths'][0]).is_file())

    def test_task_reports_do_not_delete_or_mix_unit_reports(self):
        with tempfile.TemporaryDirectory() as root:
            unit = junit(root)
            def fake_run(*args, **kwargs):
                junit(root, 'integrationTest')
                return dict(exitCode=0, timedOut=False, stdoutTail='', stderrTail='')
            with patch.object(build, '_run_subprocess', side_effect=fake_run):
                result = build.run_targeted_tests('gradle', 'Example#검증', root,
                                                  with_coverage=False, task='integrationTest')
            self.assertEqual('ok', result['status'])
            self.assertEqual(1, result['passed'])
            self.assertTrue(unit.exists())
            self.assertTrue(all('/integrationTest/' in p for p in result['reportPaths']))

    def test_timeout_bytes_are_serializable(self):
        with patch.object(build.subprocess, 'run', side_effect=subprocess.TimeoutExpired('x', 1, b'out', b'err')):
            result = build._run_subprocess(['x'], '.')
        self.assertEqual('out', result['stdoutTail'])
        json.dumps(result)

    def test_scope_filters_all_counters_and_gaps(self):
        with tempfile.TemporaryDirectory() as root:
            jacoco(root)
            parsed = build.parse_jacoco_report(root, packages=['app'], excludes=['**/dto/**'])
            gate = build.coverage_gate(root, packages=['app'], excludes=['**/dto/**'])
            unfiltered = build.coverage_gate(root)
        self.assertEqual(['app.Service'], [c['class'] for c in parsed['perClass']])
        self.assertEqual(1, parsed['overall']['CLASS']['ratio'])
        self.assertTrue(gate['pass'])
        self.assertFalse(unfiltered['pass'])

    def test_empty_scope_never_passes(self):
        with tempfile.TemporaryDirectory() as root:
            jacoco(root)
            self.assertFalse(build.coverage_gate(root, packages=['missing'])['pass'])

    def test_maven_task_list_does_not_invent_failsafe(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'pom.xml').write_text('<project/>')
            result = build.list_test_tasks(root)
        self.assertNotIn('verify', [t['task'] for t in result['tasks']])

    def test_same_project_builds_do_not_overlap(self):
        with tempfile.TemporaryDirectory() as root:
            active = 0
            maximum = 0
            guard = threading.Lock()
            def fake_run(*args, **kwargs):
                nonlocal active, maximum
                with guard:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(.03)
                junit(root)
                with guard:
                    active -= 1
                return dict(exitCode=0, timedOut=False, stdoutTail='', stderrTail='')
            with patch.object(build, '_run_subprocess', side_effect=fake_run):
                threads = [threading.Thread(target=build.run_targeted_tests,
                           args=('gradle', 'Example', root)) for _ in range(2)]
                for t in threads: t.start()
                for t in threads: t.join()
            self.assertEqual(1, maximum)

if __name__ == '__main__':
    unittest.main()

class DiscoveryOutputContract(unittest.TestCase):
    def test_task_discovery_does_not_lose_tasks_to_log_tail(self):
        import sys
        result = server._run_subprocess(
            [sys.executable, '-c', 'print("HARNESS_TEST_TASK::integrationTest"); print("x" * 6000)'],
            '.', output_limit=None)
        self.assertIn('HARNESS_TEST_TASK::integrationTest', result['stdoutTail'])
