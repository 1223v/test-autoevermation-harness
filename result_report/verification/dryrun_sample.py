"""Dry-run: call MCP tools through a real client against the Spring sample.

  .mcp-venv/bin/python dryrun_sample.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_HERE = os.path.dirname(os.path.abspath(__file__))          # result_report/verification/
ROOT = os.path.dirname(_HERE)                               # result_report/
_WORKSPACE = os.path.dirname(ROOT)                          # workspace root (plugin's parent)
PLUGIN = os.path.join(_WORKSPACE, "spring-test-harness-plugin")
MCPDIR = os.path.join(PLUGIN, "mcp")
SAMPLE = os.path.join(ROOT, "sample-spring-app")
JAR = os.path.join(MCPDIR, "javaparser-cli", "target", "astcli-1.0.0-shaded.jar")
SRC = os.path.join(SAMPLE, "src", "main", "java")


def payload(result):
    """Extract the structured/text payload from a CallToolResult."""
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc
    out = []
    for c in result.content:
        out.append(getattr(c, "text", str(c)))
    txt = "\n".join(out)
    try:
        return json.loads(txt)
    except Exception:
        return txt


async def run():
    # 1) repo-ast: extract_test_targets on the real sample sources
    env = {**os.environ, "REPO_AST_ALLOW_ROOT": SAMPLE,
           "REPO_AST_JAVAPARSER_JAR": JAR, "REPO_AST_NETWORK": "off"}
    params = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(MCPDIR, "repo_ast_server.py")], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("extract_test_targets", {"paths": [SRC]})
            data = payload(res)
            print("== repo-ast.extract_test_targets ==")
            print("  status :", data.get("status"))
            for t in data.get("testTargets", []):
                print(f"  target : {t.get('fqcn')}  kind={t.get('kind')}  "
                      f"methods={t.get('publicMethods')}")
            dg = data.get("dependencyGraph", {})
            print("  edges  :", dg.get("edges"))

    # 2) build-test: detect_build_tool on the real sample
    env2 = {**os.environ, "BUILD_TEST_NETWORK": "off", "BUILD_TEST_SCOPE": "targeted"}
    params2 = StdioServerParameters(command=sys.executable,
                                    args=[os.path.join(MCPDIR, "build_test_server.py")], env=env2)
    async with stdio_client(params2) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("detect_build_tool", {"root": SAMPLE})
            data = payload(res)
            print("== build-test.detect_build_tool ==")
            print("  result :", json.dumps(data, ensure_ascii=False))
            res2 = await s.call_tool("list_test_tasks", {"root": SAMPLE})
            print("  tasks  :", json.dumps(payload(res2), ensure_ascii=False)[:200])


if __name__ == "__main__":
    asyncio.run(run())
