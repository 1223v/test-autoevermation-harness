"""Replay official lifecycle payloads through the actual hook entry point."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / 'scripts/record-run-context.py'
PREFIX = 'test-autoevermation-harness-plugin:'

class HookLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.markers = self.root / '_workspace/.markers'
    def tearDown(self): self.tmp.cleanup()
    def event(self, name, **kw):
        p = {'hook_event_name': name, 'session_id': 'session-1', 'cwd': str(self.root), **kw}
        r = subprocess.run([sys.executable, str(REC)], input=json.dumps(p), text=True, capture_output=True)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)
    def start(self):
        return self.event('UserPromptExpansion', expansion_type='slash_command',
                          command_name=PREFIX+'full-pipeline', command_source='plugin', command_args='')
    def test_direct_slash_starts_run_with_correct_response_event(self):
        result = self.start()
        self.assertTrue((self.markers/'run.json').exists())
        self.assertEqual('UserPromptExpansion', result['hookSpecificOutput']['hookEventName'])
    def test_attempt_is_not_spawn_evidence(self):
        self.start()
        self.event('PreToolUse', tool_name='Agent', tool_input={'subagent_type': PREFIX+'spec-reviewer'})
        self.assertFalse((self.markers/'spawn-spec-reviewer.json').exists())
        self.event('SubagentStart', agent_id='child-1', agent_type=PREFIX+'spec-reviewer')
        marker=json.loads((self.markers/'spawn-spec-reviewer.json').read_text())
        self.assertEqual('child-1', marker['agent_id'])
        self.assertTrue(marker['run_id'])
    def test_other_plugin_does_not_start_or_gain_evidence(self):
        self.event('PreToolUse', tool_name='Skill', tool_input={'skill':'other:full-pipeline'})
        self.assertFalse((self.markers/'run.json').exists())
        self.start()
        self.event('SubagentStart', agent_id='other', agent_type='other:spec-reviewer')
        self.assertFalse((self.markers/'spawn-spec-reviewer.json').exists())
    def test_session_end_closes_and_new_invocation_clears_old_evidence(self):
        self.start()
        self.event('SubagentStart', agent_id='child-1', agent_type=PREFIX+'spec-reviewer')
        first=json.loads((self.markers/'run.json').read_text())
        self.event('SessionEnd', reason='clear')
        self.assertEqual('ended', json.loads((self.markers/'run.json').read_text())['status'])
        self.start()
        second=json.loads((self.markers/'run.json').read_text())
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertFalse((self.markers/'spawn-spec-reviewer.json').exists())
    def test_no_stop_event_closes_an_active_run(self):
        self.start()
        self.event('Stop')
        self.assertEqual('active', json.loads((self.markers/'run.json').read_text())['status'])
    def test_subagent_stop_records_observed_duration_without_invented_tokens(self):
        self.start()
        self.event('SubagentStart', agent_id='child-1', agent_type=PREFIX+'spec-reviewer')
        self.event('SubagentStop', agent_id='child-1', agent_type=PREFIX+'spec-reviewer')
        timing=json.loads((self.root/'_workspace/timing.json').read_text())
        self.assertGreaterEqual(timing['stages'][0]['duration_ms'],0)
        self.assertNotIn('total_tokens',timing['stages'][0])
    def test_valid_partial_final_closes_and_followup_is_not_gated(self):
        self.start()
        p=self.root/'_workspace/pipeline_result.json'
        final={'schemaVersion':2,'status':'partial','summary':'User input is required',
               'stages':{'verifyScenarios':{'status':'blocked'}}}
        p.write_text(json.dumps(final))
        self.event('PostToolUse',tool_name='Write',tool_input={'file_path':str(p),'content':p.read_text()})
        self.assertEqual('completed',json.loads((self.markers/'run.json').read_text())['status'])
        followup=self.event('PreToolUse',tool_name='Agent',tool_input={'subagent_type':PREFIX+'test-code-generator'})
        self.assertNotEqual('deny',followup.get('hookSpecificOutput',{}).get('permissionDecision'))

    def test_denied_generator_attempt_never_produces_spawn_marker(self):
        self.start()
        response=self.event('PreToolUse',tool_name='Agent',tool_input={'subagent_type':PREFIX+'test-code-generator'})
        self.assertEqual('deny',response['hookSpecificOutput']['permissionDecision'])
        self.assertFalse((self.markers/'spawn-test-code-generator.json').exists())

    def test_invalid_final_output_cannot_close(self):
        self.start()
        p=self.root/'_workspace/pipeline_result.json'
        p.write_text('{"schemaVersion":2}')
        self.event('PostToolUse',tool_name='Write',tool_input={'file_path':str(p),'content':p.read_text()})
        self.assertEqual('active',json.loads((self.markers/'run.json').read_text())['status'])

if __name__=='__main__': unittest.main()
