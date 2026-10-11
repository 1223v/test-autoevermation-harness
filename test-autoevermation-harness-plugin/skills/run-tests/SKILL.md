---
name: run-tests
description: 지정한 Spring 테스트를 실행하고 JUnit 결과를 반환한다. 테스트 실행·테스트 돌리기 요청에 사용한다. 실패해도 자동 수정하지 않는다. 결과 조회는 기존 보고서만 읽고 실행하지 않는다.
---

## 계약

[호스트 계약](../../references/host-runtime.md)과 [실행 정책](../../references/execution-policy.md)을 문맥에 없을 때만 읽는다.
build-test MCP가 필수다. 실패를 직접 셸/임의 파싱으로 대체하지 않는다.
메인이 test-runner 역할을 직접 수행한다. 역할의 상세 결과 스키마가 필요할 때만 [test-runner](../../agents/test-runner.md)를 읽는다.
`Agent(subagent_type="test-autoevermation-harness-plugin:test-runner", ...)`는 선택적 위임 예시다.

## 입력

projectRoot(확정 절대 경로), buildTool, task, targetScope{classes,packages,methods} 또는 string[], rerunTargets를 받는다.
저장 설정과 실제 요청에서 값을 확인하고 누락/모호한 대상만 질문한다. string[]는 classes로 변환한다.
methods > classes > packages 순으로 test_patterns를 만들고, test_pattern과 동시에 전달하지 않는다.
targetScope가 비면 TARGET_SCOPE_UNSPECIFIED로 범위를 확인한다. 전체 실행은 명시적 요청일 때만 ["*"]를 사용한다.
모듈은 root/task 경로로 지정하고 패키지 패턴에 넣지 않는다.
javaHome/reportDirs/coverageReportPaths/coverageTask는 확인한 값만 대응 MCP 인자로 전달한다.

## 실행

1. **조회 요청**이면 기존 TestRunResult/JUnit과 신선도만 확인한다. 낡은 결과는 stale로 표시하고 종료한다. 빌드를 실행하지 않는다.
2. buildTool/task가 확인되지 않았을 때만 detect_build_tool/list_test_tasks를 호출한다.
3. run_targeted_tests를 한 번 호출한다. 명시적 실행은 reuse_if_fresh:false(기본값), 파이프라인 검증·측정에서 요청된 결과 공유는 true다.
4. 파이프라인은 with_coverage:true로 실행한다. 단독 실행은 커버리지 포함이 요청/저장 설정에 명시된 경우만 with_coverage:true, 그 외에는 false를 전달하며 JaCoCo가 없는 프로젝트에 측정만을 위해 빌드 변경을 강요하지 않는다.
5. 응답의 passed/failed/skipped/testcases/flaky를 그대로 사용한다. 이미 반환된 JUnit 정보를 다시 parse_junit_xml로 얻지 않는다. 누락 시에만 같은 root/build_tool/task/report_dirs로 보완한다.
6. 결과를 반환한다. 실패하면 원인·잔여와 repair-tests 안내만 남기고 자동 호출하지 않는다. 파이프라인 보정 판단은 호출자가 공용 예산으로 수행한다.

Gradle은 --tests를 사용하고 Class#method를 Class.method로 매핑한다. Maven test는 -Dtest, verify는 -Dit.test다.
Maven verify는 수명주기상 단위 테스트도 실행할 수 있다. 사용자 정의 coverage_task를 추정하지 않는다.
기본 의존성 오프라인을 유지한다. 1회 온라인 동의가 있으면 해당 호출에만 online:true를 전달한다.
테스트 코드·설정은 Write/Edit하지 않는다.

## 결과

TestRunResult의 status, summary, passed, failed[], skipped, reportPaths, failureClasses, evidence, warnings, errors, nextActions를 유지한다.
MCP의 command는 executedCommand에도 매핑하고 testcases/coverageReportPaths/executionEvidence/reused를 잃지 않고 전달한다.
성공은 exitCode==0, timedOut==false, passed>0, failed=[]일 때만 가능하다. 전부 skipped·리포트 없음·기동 실패는 성공이 아니다.
flaky 이력은 경고로 보존한다. 실행하지 않은 조회를 새 실행으로 기록하지 않는다.
