"""SDK v2 startup validation and atomic indexing regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location('v2_' + name, ROOT / 'mcp' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class RuntimeV2(unittest.TestCase):
    def test_all_servers_use_sdk2_and_register_expected_tools(self):
        import asyncio
        for name, count in [('repo_ast_server', 5), ('spec_doc_server', 4), ('build_test_server', 11)]:
            module = load(name)
            server = module.build_server() if name == 'repo_ast_server' else module.mcp
            self.assertEqual(count, len(asyncio.run(server.list_tools())))

    def test_compatibility_probe_rejects_legacy_and_broken_sdk(self):
        bootstrap = load('bootstrap')
        for version in ('1.28.1', '2.1.0', '3.0.0', 'invalid'):
            with patch('importlib.metadata.version', return_value=version):
                self.assertFalse(bootstrap.current_interpreter_has_mcp())
        with patch('importlib.metadata.version', return_value='2.2.0'):
            self.assertTrue(bootstrap.current_interpreter_has_mcp())

    def test_ready_marker_does_not_skip_broken_venv(self):
        bootstrap = load('bootstrap')
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, 'requirements.installed.txt')
            marker.write_text(bootstrap.marker_payload())
            with patch.object(bootstrap, 'interpreter_has_mcp', return_value=False):
                self.assertFalse(bootstrap.deps_ready(str(marker), '/missing/python'))

    def test_broken_pip_is_repaired_before_install_and_marker_is_atomic(self):
        import subprocess
        bootstrap = load('bootstrap')
        with tempfile.TemporaryDirectory() as tmp:
            py = Path(bootstrap.venv_python(str(Path(tmp, 'venv'))))
            py.parent.mkdir(parents=True); py.touch()
            marker = Path(tmp, 'requirements.installed.txt')
            marker.write_text('stale')
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if command[1:4] == ['-m', 'pip', '--version']:
                    return subprocess.CompletedProcess(command, 1, '', 'No module named pip')
                if '--clear' in command:
                    self.assertFalse(marker.exists())
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(bootstrap, 'data_dir', return_value=tmp), \
                 patch.object(bootstrap, 'interpreter_has_mcp', return_value=True), \
                 patch.object(bootstrap.subprocess, 'run', side_effect=run):
                self.assertEqual(str(py), bootstrap.ensure_venv())
            self.assertTrue(any('--clear' in cmd for cmd in commands), commands)
            self.assertEqual(bootstrap.marker_payload(), marker.read_text())

    def test_index_remains_readable_while_replacement_is_built(self):
        module = load('spec_doc_server')
        with tempfile.TemporaryDirectory(prefix='docs-') as tmp:
            a, b = Path(tmp, 'a.md'), Path(tmp, 'b.md')
            a.write_text('Orders must retain the original index.')
            b.write_text('Replacement must be published atomically.')
            module.index_docs([str(a)])
            started, release = threading.Event(), threading.Event()
            original = module._safe_read
            def slow_read(path):
                if path == b:
                    started.set()
                    release.wait(3)
                return original(path)
            with patch.object(module, '_safe_read', side_effect=slow_read):
                thread = threading.Thread(target=module.index_docs, args=([str(b)],))
                thread.start()
                try:
                    self.assertTrue(started.wait(2))
                    self.assertEqual('ok', module.search_requirements('Orders')['status'])
                finally:
                    release.set()
                    thread.join()
            self.assertEqual('ok', module.search_requirements('Replacement')['status'])

if __name__ == '__main__': unittest.main()
