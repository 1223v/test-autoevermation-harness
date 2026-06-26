---
name: measure-coverage
description: JaCoCo로 line/branch/method/class 커버리지를 측정하고 near-100% 게이트에 미달하면 coverage-closer 에이전트로 추가 테스트를 생성해 gap을 닫는 루프를 수행한다. "커버리지 측정", "커버리지 올려줘", "coverage gap", "100% 커버리지"처럼 커버리지 측정/상향이 필요할 때 자동 호출된다.
---

## 목적

JaCoCo 리포트를 파싱해 미달 카운터와 uncovered 요소(클래스/메서드/라인/브랜치)를 식별하고, near-100% 목표에 도달할 때까지 **측정 → gap 분석 → 추가 테스트 생성 → 재측정** 루프를 돌린다. 단순 라인 채우기가 아니라 **브랜치 경로**를 실제로 검증하는 테스트를 생성한다.

근거: `[[../../RESEARCH_NOTES.md]]` §3(JaCoCo 0.8.12), §6(near-100% 정책). 게이트 도구는 build-test MCP의 `parse_jacoco_report` / `coverage_gate`.

## 호출 조건
- 자동: `full-pipeline` 의 생성·실행 단계 직후, 또는 사용자가 커버리지 상향을 요청할 때.
- 수동: `/spring-test-harness:measure-coverage`

## 입력 (HarnessConfig 일부)
```json
{
  "buildTool": "gradle|maven",
  "root": ".",
  "coverage": {
    "line": 0.95, "branch": 0.90, "method": 0.95, "class": 1.00,
    "excludes": ["**/*Application*", "**/config/**", "**/dto/**", "**/generated/**"]
  },
  "maxIterations": 3,
  "targetScope": ["com.example.orders"]
}
```
> `coverage` 임계값/제외는 `configure-harness` 인터뷰(§7 항목 d)에서 사용자가 조정 가능.

## 절차
1. **측정 실행**: test-runner(또는 build-test `run_targeted_tests(with_coverage=true)`)로 타깃 범위 테스트 + JaCoCo 리포트 생성. 네트워크 off, 최소 범위.
2. **파싱**: `mcp__build-test__parse_jacoco_report(root)` → 카운터별 overall + per-class + `uncovered[]`.
3. **게이트**: `mcp__build-test__coverage_gate(root, line, branch, method, class, mutation)` → counter별 pass/fail + gaps.
4. **분기**:
   - 게이트 통과 → 상태 `ok`, 종료.
   - 미달 → `uncovered[]`를 **coverage-closer** 에이전트에 전달:
     ```
     Task(subagent_type="coverage-closer", model="inherit",
          prompt="<uncovered[] + 대상 소스 + 제외 allowlist + 목표 임계값>")
     ```
5. **재측정 루프**: coverage-closer가 추가한 테스트를 포함해 1~3 재실행. `maxIterations` 도달 또는 게이트 통과 시 중단.
6. **수렴 실패 처리**: 잔여 gap이 남으면 `partial` 상태로 `remainingGaps[]`와 사유(예: 도달 불가 코드, 제외 후보)를 보고하고 nextActions에 "exclude 검토" 제안.

## 출력
```json
{
  "status": "ok|partial|failed",
  "summary": "라인 0.97 / 브랜치 0.92 / 메서드 0.98 / 클래스 1.00 — 게이트 통과",
  "coverage": {"line":0.97,"branch":0.92,"method":0.98,"class":1.00},
  "gatePassed": true,
  "iterations": 2,
  "addedTests": ["src/test/java/.../OrderServiceBranchTest.java"],
  "remainingGaps": [],
  "evidence": ["build/reports/jacoco/test/jacocoTestReport.xml"],
  "warnings": [], "errors": [], "nextActions": []
}
```

## 실패 유형
- `BUILD_TOOL_UNDETECTED` / `TEST_COMPILE_FAILED` / `TEST_RUNTIME_FAILED` → run-tests/repair-tests로 위임 후 재측정.
- `COVERAGE_UNREACHABLE` → 도달 불가 코드로 판단, 제외 allowlist 후보로 보고(임의 제외 금지, 사용자/설정 확인).

## 보안·성능
- 측정은 타깃 스코프로 최소화, 네트워크 off.
- per-class 결과를 캐시해 반복 측정 비용 절감.
- coverage-closer는 read+write만, Bash 금지(실행은 이 스킬이 build-test로 수행).

## 연결
- 에이전트: `coverage-closer`
- MCP: build-test(`run_targeted_tests`, `parse_jacoco_report`, `coverage_gate`), repo-ast(대상 메서드 시그니처 확인)
- 후속: 게이트 통과 시 `[[../mutation-test/SKILL.md]]` 로 진행.
