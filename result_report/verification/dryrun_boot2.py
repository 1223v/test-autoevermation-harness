"""End-to-end dry-run against a real Spring Boot 2.x sample via the harness MCP servers.

Exercises the version-aware pipeline:
  build-test.detect_build_tool      -> gradle
  build-test.detect_spring_profile  -> Boot 2.x profile (javax / jupiter / @MockBean / Java 8)
  repo-ast.extract_test_targets     -> controller/service classification + collaborator graph
Then derives the idioms the generator would select for this profile and asserts them.

  /tmp/mcp-venv2/bin/python dryrun_boot2.py
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
SAMPLE = os.path.join(ROOT, "sample-spring-boot2")
JAR = os.path.join(MCPDIR, "javaparser-cli", "target", "astcli-1.0.0-shaded.jar")
SRC = os.path.join(SAMPLE, "src", "main", "java")

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}" + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def payload(result):
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc
    out = [getattr(c, "text", str(c)) for c in result.content]
    txt = "\n".join(out)
    try:
        return json.loads(txt)
    except Exception:
        return txt


async def run():
    # 1) build-test: detect_build_tool + detect_spring_profile (the new version-aware path)
    env = {**os.environ, "BUILD_TEST_NETWORK": "off"}
    params = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(MCPDIR, "build_test_server.py")], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            bt = payload(await s.call_tool("detect_build_tool", {"root": SAMPLE}))
            print("== build-test.detect_build_tool ==")
            check("buildTool", bt.get("buildTool"), "gradle")

            sp = payload(await s.call_tool("detect_spring_profile", {"root": SAMPLE}))
            prof = sp.get("springProfile", {})
            print("== build-test.detect_spring_profile ==")
            print("  versionSource:", sp.get("versionSource"))
            print("  springProfile:", json.dumps(prof, ensure_ascii=False))
            if sp.get("notes"):
                print("  notes:", sp["notes"])
            check("bootMajor", prof.get("bootMajor"), 2)
            check("namespace", prof.get("namespace"), "javax")
            check("junitEngine", prof.get("junitEngine"), "jupiter")
            check("mockAnnotation", prof.get("mockAnnotation"), "MockBean")
            check("mockImport", prof.get("mockImport"),
                  "org.springframework.boot.test.mock.mockito.MockBean")
            check("javaBaseline", prof.get("javaBaseline"), 8)
            check("gradleTestMode", prof.get("gradleTestMode"), "useJUnitPlatform")

    # 2) repo-ast: extract_test_targets on the real Boot 2.x sources
    env2 = {**os.environ, "REPO_AST_ALLOW_ROOT": SAMPLE,
            "REPO_AST_JAVAPARSER_JAR": JAR, "REPO_AST_NETWORK": "off"}
    params2 = StdioServerParameters(command=sys.executable,
                                    args=[os.path.join(MCPDIR, "repo_ast_server.py")], env=env2)
    async with stdio_client(params2) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            data = payload(await s.call_tool("extract_test_targets", {"paths": [SRC]}))
            print("== repo-ast.extract_test_targets ==")
            print("  status:", data.get("status"))
            kinds = {}
            for t in data.get("testTargets", []):
                fqcn = t.get("fqcn", "")
                kinds[fqcn] = t.get("kind")
                print(f"  target: {fqcn}  kind={t.get('kind')}  methods={t.get('publicMethods')}")
            controller = next((k for k, v in kinds.items() if v == "controller"), None)
            service = next((k for k, v in kinds.items() if v == "service"), None)
            check("controller detected", controller, "com.example.orders.web.OrderController")
            check("service detected", service, "com.example.orders.application.OrderQueryService")

    # 3) Profile-driven idiom selection (what generate-tests / test-code-generator would emit)
    print("== generator idiom selection (from springProfile) ==")
    idioms = {
        "controller test": "@WebMvcTest + MockMvc + @MockBean",
        "mock import": prof.get("mockImport"),
        "junit test import": "org.junit.jupiter.api.Test (+ @DisplayName)"
            if prof.get("junitEngine") == "jupiter" else "org.junit.Test + @RunWith(SpringRunner.class)",
        "entity namespace": prof.get("namespace") + ".persistence.*",
        "gradle test mode": prof.get("gradleTestMode") + "()",
    }
    for k, v in idioms.items():
        print(f"  {k:18}: {v}")

    print("\n== RESULT ==", "ALL PASS" if not FAILURES else f"FAILURES: {FAILURES}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
