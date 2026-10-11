---
name: measure-coverage
description: 지정한 Spring 테스트의 JaCoCo 커버리지를 측정·조회한다. 커버리지 측정 요청은 보고서만 반환하며 테스트를 추가하지 않는다. 커버리지 상향이 명시되거나 파이프라인이 improve를 지정한 경우에만 공용 예산 안에서 gap 보정을 수행한다.
---

## 입력과 경계

[호스트 계약](../../references/host-runtime.md), [실행 정책](../../references/execution-policy.md)을 문맥에 없을 때만 읽는다.
build-test MCP가 필수다. 부족한 환경을 임의 파싱으로 대체하지 않는다.
기존 root, buildTool, coverage{line,branch,method,class,excludes}, maxIterations,
targetScope(패키지/FQCN 배열), springProfile, existingTestPaths를 받는다.
run-tests의 targetScope{classes,packages,methods}와 측정 targetScope 배열을 혼동하지 않는다.
선택 입력: operation=inspect|measure|improve(기본 measure), runResult, executionPolicy, roundId.
maxIterations는 기존 strict 무진전 추적 입력이고 새 총 상한은 executionPolicy.maxAutoFixRounds다.
신규 profile/임계값은 configure-harness에서 선택한다. 이 스킬이 조용히 모드를 바꾸지 않는다.

## 측정

1. inspect는 기존 coverage_gate와 보고서의 신선도만 보고한다. 빌드·수정하지 않는다. 낡으면 stale/partial로 표시한다.
2. measure는 정확한 테스트 범위로 `run_targeted_tests(with_coverage=true,reuse_if_fresh=true)`를 사용한다. 같은 검증 회차에서 방금 받은 runResult가 있으면 해당 보고서의 신선도를 확인해 바로 3번으로 간다.
3. `coverage_gate(root=root,line=coverage.line,branch=coverage.branch,method=coverage.method,klass=coverage.class,packages=targetScope,excludes=coverage.excludes,report_paths=runResult.coverageReportPaths,require_fresh=true,java_home=javaHome)`.
4. counters/gaps.uncovered/reportPaths를 바로 사용한다. 추가 parse_jacoco_report 호출은 하지 않는다. 기존 parse_jacoco_report 도구 자체는 독립 파싱 용도로 유지한다.
5. 결과를 저장·반환한다. 미달이어도 측정 요청은 테스트를 추가하거나 보정 질문을 띄우지 않는다. 임의 제외하지 않고 remainingGaps를 전량 보고한다.

## 명시적 개선

full-pipeline 호출에서는 초기 측정만 반환한다. 호출자가 9단계 적합성 확인 후 실패 > 적합성 > coverage 우선순위로 보정을 결정한다.
coverage-closer를 실행하려면 공용 budget reserve가 허용한 roundId가 필요하다.
직접 상향 요청은 full-pipeline의 8단계 부분 실행으로 연결하고 저장된 승인·범위·예산을 재사용한다.
현재 gaps, existingTestPaths, coverage, springProfile와 필요한 소스만 coverage-closer 역할에 전달한다.
메인이 직접 수행하거나 필요 시 `Agent(subagent_type="test-autoevermation-harness-plugin:coverage-closer", ...)`로 위임한다.
수정 전 보고서로 게이트를 다시 호출하지 않는다. 수정 후 호출자가 실행→측정→적합성 확인을 마치고 budget complete한다.
별도 중첩 루프나 budget 초기화는 금지한다. 엄격의 무진전 3회와 적합성 3라운드 종료 규칙도 유지한다.
RA 권고는 자동 제외 근거가 아니다. 예산 소진으로 보정하지 못했으면 그 이유와 남은 gap을 기록한다.

## 결과

```json
{
  "status": "partial",
  "summary": "현재 측정은 목표 미달이며 테스트 수정은 수행하지 않음",
  "coverage": {"line":0.88,"branch":0.78,"method":0.91,"class":1.0},
  "gatePassed": false,
  "iterations": 0,
  "addedTests": [],
  "remainingGaps": [{"class":"example.OrderService","counter":"BRANCH","reason":"측정된 미커버 분기"}],
  "evidence": [], "warnings": [], "errors": [], "nextActions": []
}
```

iterations는 실제 coverage 보정 횟수다. 측정만 수행하거나 다른 보정이 예산을 소진했다면 0이 유효하다.
addedTests는 closer가 반환한 addedTests[].path를 flatten한다. reportPaths/executionEvidence를 선택 보존한다.
선택 범위·보고서가 부족하면 partial/failed이고 게이트 통과를 선언하지 않는다.
보고서 자체가 없으면 JACOCO_REPORT_NOT_FOUND로 실패한다. 증거가 낡으면 결과 재사용을 거부한다.

Claude 활성 세션의 guard-gate-artifacts는 잔여 gap과 0 이상의 iterations를 확인한다. 보정 위임 여부는 요구하지 않는다.
