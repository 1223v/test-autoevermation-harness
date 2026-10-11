# 공용 실행 정책

이 문서는 요청 경계·설정 병합·보정 예산의 정본이다. 같은 문맥에서 이미 읽었으면 재읽지 않는다.
기존 단계 이름·schemaVersion:2·MCP 이름은 유지한다. 실행 주체는 두 호스트 모두 메인이 기본이며 독립 분석만 선택적으로 위임한다.

## 요청 경계

| 요청 | 수행 | 자동 테스트 수정 |
|---|---|---|
| 결과/커버리지 조회 | 기존 산출물·신선도 보고; 오래되면 stale 표시 | 없음, 빌드도 없음 |
| 테스트 실행 | run-tests, 요청 범위 1회 실행 | 없음 |
| 커버리지 측정 | measure-coverage `operation:measure`, 유효 실행 공유 또는 1회 실행 | 없음 |
| 시나리오 확인 | verify-scenarios, 보고서 갱신; 증거가 낡으면 미검증 안내 | 없음 |
| 테스트 생성/재생성 | full-pipeline | 승인 범위·예산 안에서 |
| 실패 수정/커버리지 상향 | repair-tests 또는 full-pipeline 영향 단계 | 요청된 수정·예산 안에서 |

하네스와 관계없는 “보완”, “업데이트”, “재실행”만으로 full-pipeline을 활성화하지 않는다.
부모가 호출한 스킬은 부모의 검증 회차·예약된 보정 ID를 사용한다. 자체 중첩 루프를 만들지 않는다.

## 설정

| profile | line | branch | method | class | maxAutoFixRounds |
|---|---|---|---|---|---|
| fast | .80 | .70 | .80 | 1.00 | 1 |
| balanced | .90 | .80 | .90 | 1.00 | 3 |
| strict | .95 | .90 | .95 | 1.00 | null |

최초 대화형 설정에서 한 번 선택한다(추천: balanced). 명시적 비대화형에서 모드 미지정이면 기존 strict 기본값을 유지한다.
`executionPolicy:{profile,maxAutoFixRounds,delegation:"auto"}`는 선택 필드다.
정책 없는 기존 config는 기존 coverage와 maxRepairRetries/coverageMaxIterations의 의미를 보존한다.
엄격/기존의 후자 두 값은 무진전 추적 단위이며 새 총 예산과 혼동하지 않는다.

`mcp/harness_policy.py resolve`의 stdin은 `{request:{...},saved:{...}}`, stdout은 병합된 config다.
동일 요청의 직접 지정 coverage > 명시적 profile 기본값 > 기존 값 순으로 처리한다.
profile을 명시하지 않으면 기존 custom coverage를 유지한다. 제외 목록은 모드 변경으로 초기화하지 않는다.
명시되지 않은 targets·root·버전 등은 이 함수가 추측하지 않는다. configure-harness가 실제 근거로 확정한다.
사용자가 입력·선택한 설정을 매번 다시 확인하지 않는다.

## 한 개의 보정 예산

호스트별 확정된 PLUGIN_ROOT·PLUGIN_DATA 경로로 다음을 호출한다(실제 셸에서는 placeholder 치환):

```text
node <PLUGIN_ROOT>/mcp/launch.cjs --data <PLUGIN_DATA> script <PLUGIN_ROOT>/mcp/harness_policy.py budget --root <projectRoot> --action status
```

- 예산은 `_workspace/execution-budget.json`에 저장한다. 자동 재개·세션 재시작·workspace 로테이션에서 이 파일을 보존한다. `.lock`은 공용 함수 전용이다.
- **보정 직전** `--action reserve --round-id <고유 ID> --reason test-failure|conformance|coverage`. `reserved:false`이면 수정하지 않는다.
- 최초 승인 시나리오 생성은 예산에 포함하지 않는다. 그 이후 수정 시도 한 묶음은 파일 수·성공 여부와 무관하게 1회다. 변경을 만들지 못한 시도도 소비한다.
- 자식에게 같은 round-id를 전달한다. 다른 이유로 재수정해야 하면 별도 reserve를 해야 한다.
- 수정 후 실행→측정→적합성 확인을 완료하거나 실행 불가 이유를 실제 확인해 기록한 뒤 `--action complete --round-id <ID>`.
- 예약 후 중단됐으면 해당 라운드 결과를 검증한 후 complete한다. 검증 전 추가 수정 라운드는 거부된다. 완료된 ID를 재사용해 수정할 수 없다.
- 필수 검증 후에도 미해결 항목이 있고 `remainingRounds:0`이면 결과 기록을 마치고 `partial`+`AUTO_FIX_BUDGET_EXHAUSTED`와 잔여를 보고한다. “계속할까요?” 질문을 자동으로 덧붙이지 않는다.
- 사용자가 명시적으로 계속 요청했을 때만 `--action continue --authorization <요청 식별자와 내용>`으로 현재 모드 예산만큼 추가한다. 같은 authorization 재전달은 중복 충전하지 않는다.
- 다른 테스트 생성 작업을 새로 요청했을 때만 `--action new-task --authorization <새 요청 식별자와 내용>`으로 새 예산을 시작한다. 자동 호출을 사용자 요청으로 꾸미지 않는다.
- strict/기존은 총 상한 없음. 동일 실패/gap 3회 연속 무진전이면 종료한다. 적합성 보정은 최대 3라운드, 동일 unmet이면 즉시 종료한다. 빠름·균형에도 이 더 이른 종료 조건을 적용한다.

상태가 없거나 깨졌고 07/08/09b 산출물에 기존 보정 흔적이 있으면 0회로 초기화하지 않는다. BUDGET_STATE_REQUIRED로 중단하고 복원 또는 명시적 새 예산 승인을 요청한다. 새 예산을 승인받은 경우에만 new-task와 실제 authorization을 사용한다.
호스트 전환에도 저장된 예산을 사용한다. config의 임계값을 바꾸는 것은 예산 갱신이 아니다.

## 실행 증거 공유

`run_targeted_tests(...,with_coverage=true,reuse_if_fresh=true)`는 pipeline/측정 전용 재사용 경로다.
명시적인 “테스트 실행”은 기본 `reuse_if_fresh=false`로 실제 실행한다.
소스·테스트·빌드 입력(프로젝트 .mvn, wrapper, 별도 .gradle/.gradle.kts 포함)의 추가·삭제·내용, 실행 대상·task·보고서 선택·JDK·JVM/빌드 옵션·보고서 해시를 확인한다. 하나라도 불일치하면 다시 실행한다.
돌려받은 `executionEvidence`, `reportPaths`, `coverageReportPaths`, `testcases`를 전달한다.
`coverage_gate(...,report_paths=coverageReportPaths,require_fresh=true,java_home=javaHome)`의 counters/gaps/reportPaths를 그대로 사용한다.
유효한 결과가 있으면 parse_jacoco_report를 이어서 호출하지 않는다. 독립 파싱 요청은 기존 도구를 사용할 수 있다.
JUnit 메서드 결과는 같은 실행의 testcases를 재사용하고 누락 시에만 XML을 다시 파싱한다.
커버리지 보정 역할은 새 측정 전의 보고서로 재판정하지 않는다.

## 완료

`executionSummary`에는 profile, maxAutoFixRounds, autoFixRounds, stopReason와 실제 reuseReason을 기록한다.
마지막 허용 보정에서 모두 충족되면 ok이며 stopReason은 TARGETS_MET다. 선택 목표 미달·실패·미실행·불일치는 ok가 아니다. 조회/측정은 잔여와 현재 사실을 반환하며 자동 수정하지 않는다.
토큰 수를 추정하지 않는다. 실제 관측 가능한 빌드 횟수·재사용 여부·시간만 선택적으로 기록한다.
