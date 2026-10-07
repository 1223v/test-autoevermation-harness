"""Cross-file executable examples and plugin-specific tool contracts."""
import json
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
PROSE=list((ROOT/'skills').rglob('*.md'))+list((ROOT/'agents').glob('*.md'))+list((ROOT/'references').glob('*.md'))
class PromptContract(unittest.TestCase):
    def test_all_concrete_agent_calls_resolve_to_bundled_plugin_agents(self):
        found=[]
        for p in PROSE:
            for m in re.finditer(r'subagent_type\s*=\s*"([^"<>]+)"', p.read_text()):
                name=m.group(1)
                self.assertTrue(name.startswith('test-autoevermation-harness-plugin:'),(p,name))
                self.assertTrue((ROOT/'agents'/(name.split(':')[1]+'.md')).is_file(),name)
                found.append(name)
        self.assertGreater(len(found),15)
    def test_question_examples_are_tool_json_not_invented_kwargs(self):
        questions=0
        for p in PROSE:
            text=p.read_text()
            self.assertNotRegex(text,r'AskUserQuestion\(\s*question=')
            for code in re.findall(r'```(?:json)?\n(.*?)\n```',text,re.S):
                try: data=json.loads(code)
                except ValueError: continue
                if not isinstance(data,dict) or 'questions' not in data: continue
                self.assertTrue(1<=len(data['questions'])<=4,p)
                for q in data['questions']:
                    self.assertTrue(1<=len(q['header'])<=12)
                    self.assertIsInstance(q['multiSelect'],bool)
                    self.assertTrue(2<=len(q['options'])<=4)
                    self.assertTrue(all(isinstance(o.get('label'),str) and isinstance(o.get('description'),str) for o in q['options']))
                    questions+=1
        self.assertGreater(questions,5)
    def test_agent_allowlists_use_plugin_supported_fields_and_no_user_question(self):
        for p in (ROOT/'agents').glob('*.md'):
            fm=p.read_text().split('---',2)[1]
            self.assertNotRegex(fm,r'(?m)^(permissionMode|hooks|mcpServers):')
            tools=re.search(r'(?m)^tools:\s*(.*)',fm).group(1).split(', ')
            self.assertNotIn('AskUserQuestion',tools)
            if p.stem=='source-code-analyzer': self.assertIn('LSP',tools)
    def test_no_probe_or_fake_lsp_guarantees(self):
        for p in PROSE:
            text=p.read_text()
            self.assertNotIn('첫 `AskUserQuestion` 호출이 차단·거부',text)
            self.assertNotIn('이 에이전트의 tools에 LSP 도구는 없다',text)
            self.assertNotIn('E7 통과값(항상',text)
    def test_project_skill_is_not_written_to_plugin_installation(self):
        text=(ROOT/'skills/configure-harness/SKILL.md').read_text()
        self.assertIn('.claude/skills/<skill-name>/SKILL.md',text)
        self.assertNotIn('네임스페이스: `/test-autoevermation-harness-plugin:<skill-name>`',text)

if __name__=='__main__': unittest.main()
