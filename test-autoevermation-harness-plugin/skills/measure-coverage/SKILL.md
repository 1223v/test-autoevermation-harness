---
name: measure-coverage
description: JaCoCo로 line/branch/method/class 커버리지를 측정하고 near-100% 게이트에 미달하면 coverage-closer 에이전트로 추가 테스트를 생성해 gap을 닫는 루프를 수행한다. "커버리지 측정", "커버리지 올려줘", "coverage gap", "100% 커버리지"처럼 커버리지 측정/상향이 필요할 때 자동 호출된다.
---

## 목적

JaCoCo 리포트를 파싱해 미달 카운터와 uncovered 요소(클래스/메서드/라인/브랜치)를 식별하고, near-100% 목표에 도달할 때까지 **측정 → gap 분석 → 추가 테스트 생성 → 재측정** 루프를 돌린다. 단순 라인 채우기가 아니라 **브랜치 경로**를 실제로 검증하는 테스트를 생성한다.

근거: `[[../../RESEARCH_NOTES.md]]` §3(JaCoCo 0.8.12), §6(near-100% 정책). 게이트 도구는 build-test MCP의 `parse_jacoco_report` / `coverage_gate`.

## MCP 필수 (대체 금지)

이 스킬은 `build-test` MCP 도구가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"`+remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 선검증된다.

## 호출 조건
- 자동: `full-pipeline` 의 생성·실행 단계 직후, 또는 사용자가 커버리지 상향을 요청할 때.
- 수동: `/test-autoevermation-harness-plugin:measure-coverage`

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
  "targetScope": ["com.example.orders"],
  "springProfile": { "...": "0단계 configure-harness가 확정한 버전 프로파일" },
  "existingTestPaths": ["src/test/java/com/example/orders/OrderServiceTest.java"]
}
```
> `coverage` 임계값/제외는 `configure-harness` 인터뷰(§7 항목 d)에서 사용자가 조정 가능.
> `targetScope`는 full-pipeline이 `HarnessConfig.targets`(+`targetModules`)를 매핑해 전달한다(HarnessConfig에 `targetScope`라는 필드는 없음). 이 필드는 **커버리지 측정 스코프(패키지 목록)** 로, run-tests의 실행 스코프 `targetScope{classes,packages,methods}`(객체)와 의도적으로 다른 형상이다 — 서로 그대로 전달하지 말 것.
> `maxIterations`는 full-pipeline이 `HarnessConfig.coverageMaxIterations`를 매핑해 전달한다.
> `springProfile`·`existingTestPaths`는 coverage-closer의 버전 인식 생성·중복 방지에 필수 — 미전달 시 closer가 기존 테스트 import로 판별/재탐색한다.

## 절차
1. **측정 실행**: test-runner(또는 build-test `run_targeted_tests(with_coverage=true)`)로 타깃 범위 테스트 + JaCoCo 리포트 생성. 네트워크 off, 최소 범위.
2. **파싱**: `mcp__plugin_test-autoevermation-harness-plugin_build-test__parse_jacoco_report(root)` → 카운터별 overall + per-class + `uncovered[]`.
3. **게이트**: `mcp__plugin_test-autoevermation-harness-plugin_build-test__coverage_gate(root, line, branch, method, klass, mutation)` → counter별 pass/fail + gaps. (서버 파라미터명은 `klass` — `class`는 파이썬 예약어이므로 위치 인자로 전달.) **`require_pitest`는 생략(기본 False)** — 8단계는 9단계(뮤테이션) 이전이라 PITest 리포트 부재가 정상이며, 기본값에서 부재는 `missingReports`에 포함되지 않아 JaCoCo 4카운터 전부 통과 시 `status:"ok"`가 된다. 9단계 이후의 종합 확인에서만 `require_pitest=True`로 호출한다.
4. **분기**:
   - 게이트 통과 → 상태 `ok`, 종료.
   - 미달 → `uncovered[]`를 **coverage-closer** 에이전트에 구조화 입력으로 전달(에이전트 입력 스키마와 1:1):
     ```
     Task(subagent_type="coverage-closer", model="inherit",
          prompt="""
     입력:
     {
       "projectRoot": <root 절대 경로>,
       "jacocoReportPath": <parse_jacoco_report가 읽은 XML 경로>,
       "uncovered": <parse_jacoco_report.uncovered[]>,
       "coverage": <coverage(임계값+excludes)>,
       "existingTestPaths": <existingTestPaths + 이전 반복의 addedTests 병합>,
       "buildTool": <buildTool>,
       "springProfile": <springProfile>
     }
     지시: 기존 시나리오 테스트 수정 시 scenarioRef 메서드명·javadoc 보존.
     springProfile 관용구(@MockBean/@MockitoBean·javax/jakarta·junit4/jupiter) 준수.
     CoverageCloserResult JSON으로 반환하라.
     """)
     ```
5. **재측정 루프**: coverage-closer가 추가한 테스트를 포함해 재실행한다. 게이트 통과 시 중단. `maxIterations`는 고정 상한이 아니라 **진전 추적 단위**다 — 진전(미커버 집합 감소)이 있는 한 계속하고, **동일 미커버 집합이 3회 연속(무진전)**이면 `partial`로 `remainingGaps[]`를 전량 보고 후 중단한다(fallback-policy.md #12).
6. **수렴 실패 처리**: 잔여 gap이 남으면 `partial` 상태로 `remainingGaps[]`와 사유(예: 도달 불가 코드, 제외 후보)를 보고하고 nextActions에 "exclude 검토" 제안.

**스킵 금지 (fallback-policy.md #21)**: 미달 분기에서 coverage-closer 호출은 **무조건**이다. RA advisory(리팩토링 권고) 대상이라는 이유로 루프를 건너뛸 수 없다 — advisory는 4단계 입력 필터링에만 관여하며 8단계 게이트와 무관하다. "구조적으로 커버 불가" 판단은 오케스트레이터가 아니라 **coverage-closer가 루프를 실제 수행한 뒤** `remainingGaps[].reason`으로만 내릴 수 있고, 스코프 제외는 `coverage.excludes`(사용자 승인)로만 가능하다. **무효 조건**: `gatePassed:false`인데 `iterations<1` 또는 `remainingGaps`가 비어 있는 결과는 "게이트 미수행" 산출물로 무효 — 이 상태로 반환·저장하지 말고 루프를 수행하라(`guard-gate-artifacts.py` 훅이 무효 산출물 기록을 차단한다).

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
> `addedTests`(경로 배열)는 coverage-closer 출력 `addedTests[]`(object — `{path, action, addedMethods, targetsUncovered}`)에서 `path`만 **flatten**한 것이다. 다음 반복의 `existingTestPaths`와 full-pipeline의 회귀 실행·10단계 `generatedFiles` 병합에 쓰인다.

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
