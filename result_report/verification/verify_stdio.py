"""Verify the 3 MCP servers' stdio handshake: initialize + tools/list.

Run with the venv python (which has mcp[cli] installed):
  .mcp-venv/bin/python verify_stdio.py
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_HERE = os.path.dirname(os.path.abspath(__file__))          # result_report/verification/
_REPORT = os.path.dirname(_HERE)                            # result_report/
_WORKSPACE = os.path.dirname(_REPORT)                       # workspace root (plugin's parent)
PLUGIN = os.path.join(_WORKSPACE, "spring-test-harness-plugin")
MCPDIR = os.path.join(PLUGIN, "mcp")
SAMPLE = os.path.join(_REPORT, "sample-spring-app")
JAR = os.path.join(MCPDIR, "javaparser-cli", "target", "astcli-1.0.0-shaded.jar")

SERVERS = {
    "repo-ast": ("repo_ast_server.py", {
        "REPO_AST_ALLOW_ROOT": SAMPLE,
        "REPO_AST_JAVAPARSER_JAR": JAR,
        "REPO_AST_NETWORK": "off",
    }),
    "spec-doc": ("spec_doc_server.py", {
        "SPEC_DOC_ALLOWLIST": "docs,specs,requirements",
        "SPEC_DOC_REDACT": "on",
        "SPEC_DOC_NETWORK": "off",
    }),
    "build-test": ("build_test_server.py", {
        "BUILD_TEST_NETWORK": "off",
        "BUILD_TEST_SCOPE": "targeted",
    }),
}


async def check(name: str, script: str, extra_env: dict) -> int:
    env = {**os.environ, **extra_env}
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(MCPDIR, script)],
        env=env,
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                server_name = getattr(init.serverInfo, "name", "?")
                print(f"  [{name}] initialize OK  serverInfo.name={server_name}")
                print(f"           tools/list ({len(names)}): {', '.join(names)}")
                # also list resources + prompts if present
                try:
                    res = await session.list_resources()
                    rnames = [str(r.uri) for r in res.resources]
                    if rnames:
                        print(f"           resources ({len(rnames)}): {', '.join(rnames)}")
                except Exception:
                    pass
                try:
                    pr = await session.list_prompts()
                    pnames = [p.name for p in pr.prompts]
                    if pnames:
                        print(f"           prompts ({len(pnames)}): {', '.join(pnames)}")
                except Exception:
                    pass
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [{name}] FAILED: {type(exc).__name__}: {exc}")
        return 1


async def main() -> int:
    rc = 0
    for name, (script, env) in SERVERS.items():
        rc |= await check(name, script, env)
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
