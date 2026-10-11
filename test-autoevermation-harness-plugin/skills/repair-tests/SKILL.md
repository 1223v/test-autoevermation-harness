---
name: repair-tests
description: 실패한 테스트를 고쳐달라는 명시적 요청이나 파이프라인이 예약한 보정 회차에서 원인을 확인하고 최소 diff로 수정한다. 단순 테스트 실행 실패만으로 자동 활성화하지 않는다.
---

## 입력·역할

[호스트 계약](../../references/host-runtime.md), [실행 정책](../../references/execution-policy.md)을 문맥에 없을 때만 읽는다.
failResult, originalTests, relatedSources, projectRoot, springProfile, retryCount를 사용한다.
모드 B는 failResult 대신 nonconformantItems[]와 scenarioDocs를 받아 SCENARIO_NONCONFORMANT를 보정한다.
결과/수정 불변식의 상세는 [test-fixer](../../agents/test-fixer.md), [test-code-invariants.md](../../references/test-code-invariants.md)를 필요할 때 읽는다.
위임은 선택이다: `Agent(subagent_type="test-autoevermation-harness-plugin:test-fixer", ...)`.
메인 트리에서 수정하고 이미 적용한 patches[]는 다시 적용하지 않는다. 생성된 테스트가 없는 별도 worktree에서 작업하지 않는다.

## 한 번의 보정

1. 실패 XML·컴파일 진단·target 불일치와 관련 실제 소스를 읽어 원인을 확정한다. 원인 불명은 수정하지 않고 잔여로 반환한다.
2. 부모가 전달한 roundId의 예약을 확인한다. 단독 명시적 수정은 저장 config를 이용해 공용 budget reserve를 수행한다. config가 없으면 configure-harness로 확인 가능한 값부터 구성한다.
3. test-fixer 역할을 직접 수행해 최소 diff 한 묶음을 적용한다. scenarioRef/criteriaRef를 보존하고 assertion 약화·임의 @Disabled·임의 제외를 금지한다.
4. 부모 호출에서는 patches/rerunTargets/잔여를 반환한다. 실행·예산 complete는 부모가 소유한다. 역할 내부에서 run_targeted_tests를 중복 호출하지 않는다.
5. 단독 요청에서는 실제 영향 테스트를 한 번 실행한다. 하네스 승인 시나리오가 있으면 같은 실행의 커버리지와 적합성까지 확인한다. 일반 기존 테스트에는 없는 시나리오를 만들어내지 않는다.
6. 검증 결과를 기록하고 공용 budget complete한다. 추가 수정은 새 예약이 필요하다. 예산/무진전 소진은 partial과 실제 잔여로 종료하며 자동 계속 질문을 붙이지 않는다.

## 출력

기존 RepairResult의 status, summary, patches[], rerunTargets[], retryExhausted, evidence, warnings, errors, nextActions를 유지한다.
patches[]는 적용한 변경의 증거이며 중복 적용 지시가 아니다. executionSummary/roundId는 선택적으로 기록한다.
TEST_COMPILE_FAILED, TEST_RUNTIME_FAILED, FLAKY_SUSPECTED, SPEC_MISMATCH, SYMBOL_UNRESOLVED를 구분한다.
생성·보정으로 실제 제품 결함이 드러났다면 테스트를 왜곡하지 않고 보고한다. 운영 소스 변경은 별도 사용자 요청 범위다.
