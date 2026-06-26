---
name: mutation-test
description: PITest로 뮤테이션 테스트를 실행해 mutation score를 측정하고, 살아남은 mutant가 있으면 mutation-analyst 에이전트로 단언(assertion)을 강화해 mutant를 잡는 루프를 수행한다. "뮤테이션 테스트", "mutation testing", "PIT", "테스트 강도 검증"처럼 테스트 품질 검증이 필요할 때 자동 호출된다.
---

## 목적

라인/브랜치 커버리지가 높아도 단언이 약하면 버그를 못 잡는다. PITest로 의도적 변이를 주입해 테스트가 실제로 **실패를 감지**하는지 검증하고, 살아남은 mutant를 `mutation-analyst`가 잡도록 단언을 강화한다. 목표 mutation score는 기본 0.80(조정 가능).

근거: `[[../../RESEARCH_NOTES.md]]` §4(gradle-pitest 1.19.0 / pitest-junit5-plugin 1.0.0), §6(mutationThreshold≥0.80).

## 호출 조건
- 자동: `measure-coverage` 게이트 통과 직후(커버리지 충족 후 품질 검증).
- 수동: `/spring-test-harness:mutation-test`

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
  "maxIterations": 2
}
```
> `mutation` 깊이/대상/임계값은 `configure-harness` 인터뷰(§7 항목 c)에서 사용자가 조정. `mutators`는 DEFAULTS 또는 STRONGER.

## 절차
1. **실행**: build-test로 PITest 실행(Gradle `pitest`, Maven `pitest:mutationCoverage`). `withHistory=true`로 증분, `timestampedReports=false`. 네트워크 off.
2. **파싱**: `mcp__build-test__parse_pitest_report(root)` → `mutationScore`, `survivedMutants[]{class,method,line,mutator,status}`.
3. **분기**:
   - score ≥ threshold 이고 survivors 없음(또는 허용 범위) → `ok`, 종료.
   - survivors 존재 → **mutation-analyst** 에 전달:
     ```
     Task(subagent_type="mutation-analyst", model="inherit",
          prompt="<survivedMutants[] + 대상 테스트/소스 + 목표 score>")
     ```
     - 금지: `Thread.sleep`, broad `catch`, over-mock, 의미 없는 assert 추가. mutant를 **실제로 죽이는** 단언만.
4. **재실행 루프**: 강화된 테스트로 1~2 재실행. `maxIterations` 또는 threshold 충족 시 중단.
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
