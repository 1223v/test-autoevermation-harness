"""Real Node -> bootstrap -> SDK2 stdio contract tests.

The build wrapper is a deterministic transport fixture, not a real Gradle build.
JavaParser calls use the built CLI jar and a real JDK; missing prerequisites skip
only that server's AST test. Build execution is verified separately.
"""
import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
JUNIT = '<testsuite tests="1"><testcase classname="demo.OrderTest" name="한글메서드"/></testsuite>'
JACOCO = '<report name="demo"><package name="demo"><class name="demo/Order"><counter type="LINE" missed="0" covered="1"/><counter type="BRANCH" missed="0" covered="2"/><counter type="METHOD" missed="0" covered="1"/></class></package><counter type="LINE" missed="0" covered="1"/><counter type="BRANCH" missed="0" covered="2"/><counter type="METHOD" missed="0" covered="1"/></report>'

@unittest.skipUnless(shutil.which('node') and os.name != 'nt', 'POSIX Node transport fixture required; Windows validated separately')
class StdioV2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harness stdio ')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'docs').mkdir()
        self.doc = self.project / 'docs/orders.md'
        self.doc.write_text('Orders must reject negative quantities.\n\nScenario: Reject order\nGiven an order\nWhen quantity is negative\nThen reject the order\n')
        self.java = self.project / 'src/main/java/demo/Order.java'
        self.java.parent.mkdir(parents=True)
        self.java.write_text('package demo; import org.springframework.stereotype.Service; @Service public class Order { public int total() { return 1; } }')
        test = self.project / 'src/test/java/demo/OrderTest.java'
        test.parent.mkdir(parents=True)
        test.write_text('package demo; public class OrderTest { public void 한글메서드() {} }')
        (self.project / 'build.gradle').write_text("plugins { id 'java'; id 'jacoco'; id 'org.springframework.boot' version '3.4.5' }\n")
        driver = self.project / 'fixture.py'
        driver.write_text('from pathlib import Path\nimport sys\nif "help" in sys.argv:\n print("HARNESS_TEST_TASK::test")\nelse:\n p=Path("build/test-results/test/TEST-demo.OrderTest.xml"); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('+repr(JUNIT)+')\n p=Path("build/reports/jacoco/test/jacocoTestReport.xml"); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('+repr(JACOCO)+')\n')
        wrapper = self.project / 'gradlew'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(driver)) + ' "$@"\n')
        wrapper.chmod(0o755)

    def client(self, server):
        env = dict(os.environ, PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH',''),
                   CLAUDE_PLUGIN_DATA=str(self.project/'plugin-data'), REPO_AST_ALLOW_ROOT=str(self.project),
                   SPEC_DOC_WORKSPACE=str(self.project), SPEC_DOC_ALLOWLIST='docs', BUILD_TEST_ALLOW_NETWORK='0')
        return Client(StdioServerParameters(command=shutil.which('node'),
                      args=[str(ROOT/'mcp/launch.cjs'), str(ROOT/'mcp'/f'{server}_server.py')],
                      cwd=str(self.project), env=env), read_timeout_seconds=60)

    async def call(self, client, name, arguments=None):
        result = await client.call_tool(name, arguments or {})
        self.assertFalse(result.is_error, (name, result.content))
        data = result.structured_content
        if data is None:
            data = json.loads(''.join(c.text for c in result.content if c.type == 'text'))
        self.assertIsInstance(data, dict)
        self.assertNotEqual('failed', data.get('status'), (name, data))
        return data

    async def invalid_then_health(self, client, name, arguments):
        result = await client.call_tool(name, arguments)
        self.assertTrue(result.is_error, (name, result))
        self.assertIn('server', await self.call(client, 'health'))

    async def test_spec_doc_four_tools_and_invalid_input(self):
        async with self.client('spec_doc') as client:
            self.assertEqual({'health','index_docs','search_requirements','extract_acceptance_criteria'}, {t.name for t in (await client.list_tools()).tools})
            await self.call(client,'health')
            indexed = await self.call(client,'index_docs',{'paths':[str(self.doc)]})
            self.assertEqual('ok',indexed['status'])
            found = await self.call(client,'search_requirements',{'query':'Orders'})
            self.assertEqual('ok',found['status'])
            await self.call(client,'extract_acceptance_criteria',{'paths':[str(self.doc)]})
            await self.invalid_then_health(client,'index_docs',{'paths':123})

    async def test_build_eleven_tools_and_invalid_input(self):
        async with self.client('build_test') as client:
            names = {t.name for t in (await client.list_tools()).tools}
            calls = [('health',{}), ('detect_build_tool',{}), ('detect_spring_profile',{}),
                     ('list_test_tasks',{}), ('detect_build_capabilities',{}),
                     ('check_dependency_cache',{'build_tool':'gradle'}),
                     ('run_targeted_tests',{'build_tool':'gradle','test_patterns':['demo.OrderTest#한글메서드']}),
                     ('parse_junit_xml',{'build_tool':'gradle','task':'test'}),
                     ('parse_jacoco_report',{'packages':['demo']}),
                     ('coverage_gate',{'packages':['demo']}), ('detect_pipeline_state',{'packages':['demo']})]
            self.assertEqual(names,{n for n,_ in calls})
            for name,args in calls:
                if name != 'health': args['root']=str(self.project)
                data = await self.call(client,name,args)
                if name == 'run_targeted_tests':
                    self.assertEqual('ok',data['status']); self.assertEqual(1,data['passed'])
                    self.assertTrue(all(Path(p).is_file() for p in data['reportPaths']))
            await self.invalid_then_health(client,'run_targeted_tests',{})
            bad = await client.call_tool('run_targeted_tests',{'build_tool':'gradle','test_pattern':'A;exit','root':str(self.project)})
            self.assertIn('INVALID',str(bad.content).upper())

    async def test_repo_ast_five_tools_and_invalid_input(self):
        if not shutil.which('java') or not list((ROOT/'mcp/javaparser-cli/target').glob('*shaded.jar')):
            self.skipTest('Build JavaParser CLI jar and install a JDK for AST transport validation')
        async with self.client('repo_ast') as client:
            calls=[('health',{}), ('parse_java_file',{'path':str(self.java)}),
                   ('resolve_symbol',{'paths':[str(self.java)],'symbol':'demo.Order'}),
                   ('list_spring_components',{'paths':[str(self.java)]}),
                   ('extract_test_targets',{'paths':[str(self.java)]})]
            self.assertEqual({n for n,_ in calls},{t.name for t in (await client.list_tools()).tools})
            for name,args in calls:
                data = await self.call(client,name,args)
                if name != 'health':
                    self.assertTrue(data['testTargets'], data)
            await self.invalid_then_health(client,'parse_java_file',{})

if __name__ == '__main__': unittest.main()
