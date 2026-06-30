"""Dry-run the harness AST classifier against a real custom-component sample.

Imports the SHIPPING analysis functions from repo_ast_server.py directly (the
pure-Python regex extractor — the default path when the JavaParser jar is not
built). No `mcp` package and no jar required, so it exercises exactly what most
users hit out of the box.

Collects evidence for the three "partial / degraded" custom-component cases:
  1. custom meta-stereotype  (@UseCase  -> @Component)            distance 1
  2. transitive meta-stereotype (@ReadModel -> @UseCase -> @Component) distance 2
  3. custom composed request-mapping annotation (@GetJson -> @RequestMapping)
  4. custom ConstraintValidator (no stereotype) -> must still be a target

Run:  python3 dryrun_custom_components.py
Exit 0 if observations match the expected (pre- or post-fix) snapshot passed via
--expect {baseline|fixed}; defaults to printing observations only.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))      # result_report/verification/
ROOT = os.path.dirname(_HERE)                            # result_report/
_WORKSPACE = os.path.dirname(ROOT)                       # workspace root
PLUGIN = os.path.join(_WORKSPACE, "spring-test-harness-plugin")
MCPDIR = os.path.join(PLUGIN, "mcp")
SAMPLE_SRC = os.path.join(ROOT, "sample-custom-components", "src", "main", "java")


def _load_module():
    """Import repo_ast_server.py without the mcp SDK (import is guarded)."""
    path = os.path.join(MCPDIR, "repo_ast_server.py")
    spec = importlib.util.spec_from_file_location("repo_ast_server_dryrun", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    expect = "print"
    for a in sys.argv[1:]:
        if a.startswith("--expect="):
            expect = a.split("=", 1)[1]

    os.environ["REPO_AST_ALLOW_ROOT"] = SAMPLE_SRC
    os.environ["REPO_AST_NETWORK"] = "off"
    # Force the pure-Python path so the run is deterministic regardless of any jar.
    os.environ["REPO_AST_JAVAPARSER_JAR"] = "/nonexistent-force-regex.jar"

    mod = _load_module()

    # extract_test_targets equivalent: _analyze with no kinds filter.
    full = mod._analyze([SAMPLE_SRC])
    by_fqcn = {t["fqcn"]: t for t in full["testTargets"]}

    # list_spring_components equivalent: only stereotype kinds.
    comps = mod._analyze([SAMPLE_SRC], kinds=["controller", "service", "repository", "component"])
    discovered = {t["fqcn"] for t in comps["testTargets"]}

    def kind_of(simple):
        for fqcn, t in by_fqcn.items():
            if fqcn.endswith("." + simple):
                return t["kind"]
        return None

    def risk_of(simple):
        for fqcn, t in by_fqcn.items():
            if fqcn.endswith("." + simple):
                return t.get("riskPoints") or full.get("riskPoints") or []
        return []

    usecase = "com.example.custom.application.CreateOrderUseCase"
    readmodel = "com.example.custom.application.OrderSummaryReadModel"
    controller = "com.example.custom.web.OrderApiController"
    validator = "com.example.custom.validation.PositiveAmountValidator"

    obs = {
        "UseCase.kind": kind_of("CreateOrderUseCase"),
        "UseCase.discoveredByListComponents": usecase in discovered,
        "ReadModel.kind": kind_of("OrderSummaryReadModel"),
        "ReadModel.discoveredByListComponents": readmodel in discovered,
        "Controller.kind": kind_of("OrderApiController"),
        "Controller.discovered": controller in discovered,
        "Validator.kind": kind_of("PositiveAmountValidator"),
        "Validator.isTarget": validator in by_fqcn,
    }
    # Composed-mapping risk surfaced anywhere (target-level or top-level)?
    composed_flag = any(
        "GetJson" in str(r) or "composed" in str(r).lower()
        for r in (full.get("riskPoints") or [])
    ) or any(
        "GetJson" in str(w) or "composed" in str(w).lower()
        for w in (full.get("warnings") or [])
    )
    obs["ComposedMapping.flagged"] = composed_flag

    print("== custom-component dry-run (regex path) ==")
    print("  status:", full.get("status"), " degraded:", full.get("degraded"))
    print("  discovered components:", sorted(discovered))
    print("  riskPoints:", full.get("riskPoints"))
    print("  warnings:", full.get("warnings"))
    print("  --- observations ---")
    for k, v in obs.items():
        print(f"    {k:38} = {v!r}")

    baseline = {
        "UseCase.kind": "pojo",
        "UseCase.discoveredByListComponents": False,
        "ReadModel.kind": "pojo",
        "ReadModel.discoveredByListComponents": False,
        "Controller.kind": "controller",
        "Controller.discovered": True,
        "Validator.kind": "pojo",
        "Validator.isTarget": True,
        "ComposedMapping.flagged": False,
    }
    fixed = {
        "UseCase.kind": "component",
        "UseCase.discoveredByListComponents": True,
        "ReadModel.kind": "component",
        "ReadModel.discoveredByListComponents": True,
        "Controller.kind": "controller",
        "Controller.discovered": True,
        "Validator.kind": "pojo",
        "Validator.isTarget": True,
        "ComposedMapping.flagged": True,
    }

    if expect in ("baseline", "fixed"):
        want = baseline if expect == "baseline" else fixed
        fails = [k for k in want if obs.get(k) != want[k]]
        print(f"\n== EXPECT {expect} ==", "MATCH" if not fails else f"MISMATCH: {fails}")
        for k in fails:
            print(f"    {k}: got {obs.get(k)!r}, want {want[k]!r}")
        return 0 if not fails else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
