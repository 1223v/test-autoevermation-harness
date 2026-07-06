---
name: mutation-test
description: PITest로 뮤테이션 테스트를 실행해 mutation score를 측정하고, 살아남은 mutant가 있으면 mutation-analyst 에이전트로 단언(assertion)을 강화해 mutant를 잡는 루프를 수행한다. "뮤테이션 테스트", "mutation testing", "PIT", "테스트 강도 검증"처럼 테스트 품질 검증이 필요할 때 자동 호출된다.
---

## 목적

라인/브랜치 커버리지가 높아도 단언이 약하면 버그를 못 잡는다. PITest로 의도적 변이를 주입해 테스트가 실제로 **실패를 감지**하는지 검증하고, 살아남은 mutant를 `mutation-analyst`가 잡도록 단언을 강화한다. 목표 mutation score는 기본 0.80(조정 가능).

근거: `[[../../RESEARCH_NOTES.md]]` §4(gradle-pitest 1.19.0 / pitest-junit5-plugin 1.0.0), §6(mutationThreshold≥0.80).

## MCP 필수 (대체 금지)

이 스킬은 `build-test` MCP 도구가 **필수**다. 도구 미가용(도구 없음·호출 실패·연결 끊김)이면 Grep/Read/직접 파싱으로 **대체하지 말고** `status:"failed"` + remediation(fallback-policy #20)으로 즉시 중단한다. 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 연결이 검증되어 있어야 한다.

## 호출 조건
- 자동: `measure-coverage` 게이트 통과 직후(커버리지 충족 후 품질 검증).
- 수동: `/test-autoevermation-harness-plugin:mutation-test`

## 입력 (HarnessConfig 일부)
```json
{
  "buildTool": "gradle|maven",
  "root": ".",
  "mutation": {
    "targetClasses": ["com.example.orders.*"],
    "targetTests": ["com.example.orders.*Test"],
    "mutators": "DEFAULTS",
    "mutationThreshold": 0.80,
    "threads": 2
  },
  "maxIterations": 3,
  "springProfile": { "...": "0단계 configure-harness가 확정한 버전 프로파일" },
  "existingTestPaths": ["src/test/java/com/example/orders/OrderServiceTest.java"]
}
```
> `mutation` 깊이/대상/임계값은 `configure-harness` 인터뷰(§7 항목 c)에서 사용자가 조정. `mutators`는 DEFAULTS 또는 STRONGER.
> `maxIterations`는 full-pipeline이 `HarnessConfig.mutationMaxIterations`를 매핑해 전달한다.
> `existingTestPaths`는 full-pipeline이 5단계 생성 파일 + 8단계 `addedTests`를 병합해 전달한다.

## 절차
1. **실행**: build-test로 PITest 실행(Gradle `pitest`, Maven `org.pitest:pitest-maven:mutationCoverage`). `withHistory=true`로 증분, `timestampedReports=false`. 네트워크 off.
2. **파싱**: `mcp__build-test__parse_pitest_report(root)` → `mutationScore`, `survivedMutants[]{class,method,line,mutator,status}`.
3. **분기**:
   - score ≥ threshold 이고 survivors 없음(또는 허용 범위) → `ok`, 종료.
   - survivors 존재 → **mutation-analyst** 에 구조화 입력으로 전달(에이전트 입력 스키마와 1:1):
     ```
     Task(subagent_type="mutation-analyst", model="inherit",
          prompt="""
     입력:
     {
       "projectRoot": <root 절대 경로>,
       "pitestReportPath": <parse_pitest_report가 읽은 mutations.xml 경로>,
       "survivedMutants": <parse_pitest_report.survivedMutants[]>,
       "mutationThreshold": <mutation.mutationThreshold>,
       "existingTestPaths": <existingTestPaths>,
       "buildTool": <buildTool>,
       "springProfile": <springProfile>
     }
     지시: 기존 시나리오 테스트의 scenarioRef 메서드명·javadoc 보존(단언만 강화).
     새 파일 생성 시 springProfile 관용구(junit4/jupiter·@MockBean/@MockitoBean·javax/jakarta) 준수.
     MutationAnalystResult JSON으로 반환하라.
     """)
     ```
     - 금지: `Thread.sleep`, broad `catch`, over-mock, 의미 없는 assert 추가. mutant를 **실제로 죽이는** 단언만.
4. **재실행 루프**: 강화된 테스트로 재실행한다. threshold 충족 시 중단. `maxIterations`는 고정 상한이 아니라 **진전 추적 단위**다 — 진전(생존 mutant 감소)이 있는 한 계속하고, **동일 survivor 집합이 3회 연속(무진전)**이면 `partial`로 `survivingMutants[]`(+동등 mutant 사유)를 전량 보고 후 중단한다(fallback-policy.md #12).
5. **수렴 실패**: 잔여 survivor는 `partial`로 보고하고 `survivingMutants[]`에 사유(동등 mutant 가능성 포함) 명시. 동등(equivalent) mutant 의심은 임의 무시하지 말고 보고.

## 출력
```json
{
  "status": "ok|partial|failed",
  "summary": "mutation score 0.86 — 목표 0.80 충족, survivors 3개 강화로 제거",
  "mutationScore": 0.86,
  "thresholdMet": true,
  "iterations": 1,
  "killedMutants": 17,
  "strengthenedTests": ["src/test/java/.../OrderServiceTest.java"],
  "survivingMutants": [],
  "evidence": ["build/reports/pitest/mutations.xml"],
  "warnings": [], "errors": [], "nextActions": []
}
```

## 실패 유형
- `PITEST_RUN_FAILED` → 빌드/플러그인 설정 점검(예: junit5PluginVersion 누락) 후 재시도.
- `EQUIVALENT_MUTANT_SUSPECTED` → 강화 불가 사유 보고, 임계값 조정은 사용자 확인.

## 보안·성능
- `targetClasses` 범위 한정으로 실행 비용 절감, `threads`는 보수적.
- `withHistory`로 증분 실행.
- mutation-analyst는 read+write만, Bash 금지(실행은 이 스킬이 수행).

## 연결
- 에이전트: `mutation-analyst`
- MCP: build-test(PITest 실행 + `parse_pitest_report`), repo-ast(대상 메서드 확인)
- 선행: `[[../measure-coverage/SKILL.md]]`(커버리지 게이트 통과 후 실행)
