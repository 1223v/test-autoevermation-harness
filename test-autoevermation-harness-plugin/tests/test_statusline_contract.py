"""Statusline integration uses the invoking plugin root and explicit consent."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
def load(relative):
    spec=importlib.util.spec_from_file_location('statusline_contract', ROOT/relative)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

class StatuslineContract(unittest.TestCase):
    def test_private_registry_cannot_override_invoking_plugin_root(self):
        mod=load('hooks/statusline-autosetup.py')
        with tempfile.TemporaryDirectory() as tmp:
            registry=Path(tmp)/'registry.json'
            registry.write_text(json.dumps({'plugins': {'test-autoevermation-harness-plugin@other-market': [{'installPath':'/wrong-install'}]}}))
            with patch.object(mod,'INSTALLED_PLUGINS',str(registry),create=True):
                self.assertEqual(mod.PLUGIN_ROOT,mod.resolve_install_path())

    def test_version_follows_root_refreshed_by_session_hook(self):
        mod=load('scripts/test-autoevermation-statusline.py')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'active'; (root/'.claude-plugin').mkdir(parents=True)
            (root/'.claude-plugin/plugin.json').write_text('{"version":"2.0.0"}')
            registry=Path(tmp)/'registry.json'
            registry.write_text('{"plugins":{"test-autoevermation-harness-plugin@other":[{"installPath":"/old"}]}}')
            cfg={'pluginRoot':str(root),'installPath':str(root)}
            with patch.object(mod,'INSTALLED_PLUGINS',str(registry),create=True):
                self.assertEqual('2.0.0',mod.read_version(cfg))
                self.assertTrue(mod.plugin_present(cfg))
                self.assertFalse(mod.plugin_present({'installPath':'/missing'}))

    def test_optional_statusline_never_probes_input_or_assumes_consent(self):
        mod=load('hooks/statusline-autosetup.py')
        prompt=mod.consent_prompt_text()
        self.assertIn('main conversation',prompt)
        self.assertIn('Do not probe',prompt)
        self.assertIn('unanswered',prompt)

if __name__=='__main__': unittest.main()
