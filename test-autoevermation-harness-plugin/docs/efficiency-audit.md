# 실행 비용·사용 흐름 개선 기록

조사·구현 시작: 2026-10-09. 최종 확인: 2026-10-11. 승인된 대화 계획을 구현한다. 기존 미커밋 호환성 작업은 유지한다.
변경 전 파일/크기 기록은 저장소의 무시된 `_workspace/efficiency-redesign/before/`에 보존했다.

## 조사 근거와 결정

| 우선순위 | 근거(변경 전) | 영향 | 결정 |
|---|---|---|---|
| P1 | [full-pipeline](../skills/full-pipeline/SKILL.md), 변경 전 3·31행 | 포괄적인 호출 조건·강제 위임 | 목적별 경로, 직접 수행 기본 |
| P1 | [measure-coverage](../skills/measure-coverage/SKILL.md), 변경 전 45–73행 | 측정 요청도 수정·반복, maxIterations는 상한 아님 | 측정/개선 분리, 공용 보정 예산 |
| P1 | [실행 증거 공유](../references/execution-policy.md#실행-증거-공유), 변경 전 full-pipeline 526행 | 마지막 측정 후 중복 회귀 실행 | 같은 실행 범위·지문이면 결과 공유 |
| P2 | [coverage-closer](../agents/coverage-closer.md), 변경 전 127행 | 수정 전 보고서 재검사 | 전달된 gap만 사용, 수정 후 메인이 측정 |
| P2 | [configure-harness](../skills/configure-harness/SKILL.md), 변경 전 240–517행 | 분산 인터뷰·선택 기능 질문 | 누락 값만 묶어서 질문 |
| P2 | [host-runtime](../references/host-runtime.md), 변경 전 8행 | 역할마다 공통 문서 재읽기 | 현재 문맥에서 재사용, 상세는 필요 시 로드 |
| P2 | full-pipeline 754줄 / configure-harness 611줄 | 긴 지침과 중복 계약 | 각 300줄 이하, 정본 참조 분리 |

공식 문서는 2026-10-08 조사 후 2026-10-09 재확인했다.
- [OpenAI Build skills](https://developers.openai.com/plugins/build/skills): 사용자 목적별 스킬, 간결한 본문과 조건부 참조.
- [Claude Skills](https://code.claude.com/docs/en/skills): 500줄 미만 본문과 지원 파일 분리. 이 프로젝트는 300줄을 목표로 한다.
- [Claude Hooks](https://code.claude.com/docs/en/hooks): PreToolUse 결정 봉투·세션 범위는 보존하고 spawn 강제만 제거한다.
- [JaCoCo 0.8.12 counters](https://raw.githubusercontent.com/jacoco/jacoco/v0.8.12/org.jacoco.doc/docroot/doc/counters.html): 카운터는 실행 증거이며 요구사항 충족과 동일하지 않으므로 시나리오 검증을 유지한다.
- [Gradle JaCoCo](https://docs.gradle.org/current/userguide/jacoco_plugin.html): 테스트와 보고서 생성을 함께 구성할 수 있다. 기존 Gradle 8.12 fixture의 명령을 재사용하며 새 Gradle API를 도입하지 않는다.

의존성 선언: Python >=3.10, MCP >=2.2,<3, packaging >=26.1,<27, JavaParser 3.28.2. 변경하지 않는다.
모드 임계값과 보정 횟수는 사용자 확정 정책이며 공식 권장값이 아니다.

## TODO / 구현 기록

- [x] 공용 실행 정책·지속되는 총 보정 예산
- [x] 실행 증거·커버리지 결과 공유
- [x] 직접 수행을 허용하는 훅과 승인·결과 검사
- [x] 핵심 스킬 축소·조회/실행/수정 경로 분리
- [x] 양쪽 가이드·관련 기존 검사 조정
- [x] 기존 검사·실제 빌드·비용 비교

결정: 현재 브랜치에서 작업한다. 별도 워크트리 이동은 미커밋 호환성 변경을 누락하므로 하지 않는다.
결정: 사용자가 허용한 관련 기존 검사만 수정한다. 새 테스트 파일·의무 TDD·중복 리뷰는 추가하지 않는다.
결정: 사라진 timedOut 필드 문제 후보는 현재 작업본에서 해결되어 재작업하지 않는다.

## 구현 위치

- [harness_policy.py](../mcp/harness_policy.py): 모드 병합·지속되는 총 보정 예산·중복 예약/계속 요청 처리. 정책 없는 기존 설정은 자동 전환하지 않는다.
- [build_test_server.py](../mcp/build_test_server.py): run_targeted_tests의 선택 reuse_if_fresh, coverage_gate의 선택 require_fresh/java_home와 실행 증거 참조. 기존 이름·필수 인자·기본 오프라인 유지.
- [guard-gate-artifacts.py](../scripts/guard-gate-artifacts.py), [record-run-context.py](../scripts/record-run-context.py): 직접 수행 허용, spawn 필수 조건 제거, 승인·선행 산출물·결과 검사 유지. executionSummary는 저장 정책/예산과 대조한다. 일반 사용자 편집을 자동 보정으로 간주하는 새 쓰기 차단은 추가하지 않는다.
- [공용 정책](../references/execution-policy.md), [전체 흐름](pipeline-flow.md), [Claude 사용 가이드](GUIDE.md), [Codex 사용 가이드](CODEX.md): 요청 경계·질문 묶기·설정/환경 재사용·자동 재개 규칙.

## 검증 결과

환경: Windows, Python 3.14.0, MCP SDK 2.3.0, JDK 17.0.7, Gradle 8.12, Maven 3.9.9. 기존 Boot 3.2.0·JaCoCo 0.8.12 통합 fixture와 기존 설치 SDK를 사용했다. 의존성 선언은 변경하지 않았다.

| 확인 | 결과·한계 |
|---|---|
| 기존 unittest 전체 | 변경 전 197개/5.942초 → 최종 199개/7.491초. 양쪽 모두 실패 이벤트 16·오류 4·skip 3. 실패 이름 집합이 동일하여 신규 실패 0건. 전체 통과는 아니다. subTest 이벤트 수를 통과 테스트 수로 환산하지 않았다. |
| 관련 기존 검사 | 빠름 1·균형 3회에서 실패/적합성/커버리지 합산, 중첩 예약 차단, 예약 완료 후 ID 재사용 차단, 재개 지속, 명시적 계속 요청의 중복 충전 방지 확인. 기존 승인 전 차단 검사는 유지. |
| 실행 재사용 검사 | 소스·테스트·빌드·JDK/JVM 옵션·task·보고서 변경, 실패 증거, .mvn 설정·wrapper·별도 Gradle 스크립트 추가/수정/삭제를 기존 검사에 추가해 확인. 조회/게이트 호출 중 테스트 바이트 불변 확인. |
| 기존 실제 빌드 runner | tests/integration/verify_real_builds.py 완료. Gradle/Maven 각각 일반·한글 메서드·통합 테스트, 전체 skip·패턴 불일치·컴파일 실패·보정·커버리지 범위 사례 통과. 전체 약 58.49초. 실패를 기대한 사례의 failed는 정상 결과다. |
| 최초 통합 시도 | 기본 한글 사용자 Gradle 캐시에서 GradleWorkerMain 로딩 실패. 기존 검증의 영문 GRADLE_USER_HOME으로 맞춘 뒤 위 runner 완료. 기본 캐시 환경의 문제를 이번 변경으로 해결했다고 주장하지 않는다. |
| 실제 MCP stdio | 현재 소스의 Node → bootstrap → SDK stdio 연결. Codex/Claude 환경 각각 repo-ast 5·spec-doc 4·build-test 11개 도구 노출, health 6회 오류 없음. spec 인덱스/추출과 JUnit 파싱 ok. AST는 Service 애노테이션 미해결 1건으로 partial이며 이를 성공으로 바꾸지 않았다. |
| 호스트 승인 | 기존 훅 검사와 양쪽 호스트 지침에서 승인 전 차단·승인 범위·무응답 비승인 유지. 실제 Codex/Claude 모델의 승인→생성 전체 대화, Claude LSP/UI·상태줄, 다른 OS/JDK 조합은 미실행. |

재현 명령(기존 SDK Python, UTF-8 환경):

```text
python -m unittest discover -s test-autoevermation-harness-plugin/tests -q
python -m unittest discover -s test-autoevermation-harness-plugin/tests -k shared_execution -v
python test-autoevermation-harness-plugin/tests/integration/verify_real_builds.py <새 출력 디렉터리>
```

마지막 명령에는 JAVA_HOME=JDK17, Gradle8.12/Maven3.9.9 PATH와 확인된 영문 GRADLE_USER_HOME을 사용한다. 초기 fixture 의존성 다운로드는 기존 runner의 명시적 online=True다. 프로젝트 기본 온라인 정책을 변경하지 않는다.

원시 로컬 기록: [전체 검사](../../_workspace/efficiency-redesign/final-tests.log), [기준 대비 실패 목록](../../_workspace/efficiency-redesign/test-comparison.json), [실제 빌드](../../_workspace/efficiency-redesign/integration-ascii-cache.log), [실행 공유 관측](../../_workspace/efficiency-redesign/execution-sharing.json), [MCP](../../_workspace/efficiency-redesign/stdio-results.json). _workspace는 배포 대상이 아닌 로컬 관측 자료이며 핵심 수치는 이 문서에 보존한다. 기존 실패 분류는 [호환성 작업 기록](compatibility-remediation.md#기존-검사에서-남은-실패)을 참조한다.

## 비용 비교

동일 fixture의 테스트 범위(demo.CountTest + demo.OtherTest)·입력·JDK를 유지하여 최초 테스트+커버리지 실행 직후 재사용 호출을 관측했다. 재사용 결과의 실행 ID와 테스트 3개 결과가 같고 최신 coverage_gate도 통과했다.

| 관측 | Gradle | Maven |
|---|---:|---:|
| 최초 실행 시간 | 11.985초 | 4.291초 |
| 최초 subprocess 호출 | 2 (구성 탐지 + 테스트/계측) | 1 (테스트/계측) |
| 후속 재사용 시간 | 0.032초 | 0.028초 |
| 후속 추가 subprocess | 0 | 0 |
| 후속 추가 대상 테스트 실행 | 0 | 0 |

이는 한 번의 관측이며 전체 사용자 세션의 속도 개선률이 아니다. 최종 build-control 지문 보강 후에는 관련 기존 검사로 추가/변경/삭제 무효화를 확인했고 전체 실제 빌드 행렬을 중복 실행하지 않았다.

| 지침 크기 실측 | 변경 전 | 변경 후 |
|---|---:|---:|
| full-pipeline/SKILL.md | 754줄 / 62,220 bytes | 94줄 / 10,293 bytes |
| configure-harness/SKILL.md | 611줄 / 29,572 bytes | 108줄 / 8,691 bytes |

본문 원문 UTF-8 크기이며 실제 읽힌 지침 총량·토큰 수가 아니다. 상세 계약은 조건부 참조로 이동했다. 실제 호스트의 읽기 로그·토큰 정보를 수집하지 않았으므로 토큰 절감률을 추정하지 않는다.

아래는 같은 정상 생성 동선에서의 **지침상 호출 비교**로, 실제 대화 측정값과 구분한다. 조건은 대상/설정 확정, 환경 준비됨, 권고 존재, 사용자 시나리오 승인, 보정 없이 목표 충족이다.

| 항목 | 변경 전 지시 | 변경 후 지시 |
|---|---|---|
| 권고·시나리오 질문 | 별도 권고 선택 + 시나리오 승인 2회 | 권고를 함께 보여주는 시나리오 승인 1회 |
| 유효 설정/재개·선택 스킬 저장 | 재개 단계/추가 설정/저장 질문 경로 존재 | 새 누락·충돌만 질문, 저장은 요청 시만 |
| 대상 테스트·계측 | run-tests 실행 뒤 measure-coverage가 다시 실행 | 동일 검증 회차 1회 공유 |
| 별도 회귀 실행 | 커버리지 보정 뒤 별도 실행 지시 | 마지막 검증이 전체 범위를 포함하면 0회 |
| 중복 도구 호출 | gate 후 별도 파싱, coverage-closer가 수정 전 gate 재호출 | gate 카운터/gap 공유, 수정 후에만 검증 |
| 위임 | Claude 각 단계 Agent 필수 | 양쪽 메인 직접 수행, 독립 분석만 선택 |

실제 질문 수·읽기량·전체 세션 관측 시간은 모델 대화를 실행해야 측정할 수 있다. 위 표를 실측 절감률로 해석하지 않는다.

## 최종 검토와 결정

executing-plans의 전체 변경 읽기 전용 검토를 한 번 수행했다. 중복 검토·새 테스트 파일·의무 TDD·커밋은 추가하지 않았다.

- 중요 발견 해결: .mvn 설정, wrapper, 별도 .gradle/.gradle.kts, MAVEN_ARGS가 바뀌면 재사용을 무효화하도록 보강했다. [Maven 공식 설정](https://maven.apache.org/configure.html)의 프로젝트/JVM 옵션 계약을 2026-10-11 확인했다. 기존 재사용 검사 1개에 해당 사례를 확장해 통과했으며 최종 전체 검사에 신규 실패는 없다.
- 사소한 항목 보류: verify-scenarios의 절차 표제에 “subagent 호출” 표현이 남아 있다. 본문은 직접 수행 기본·위임 선택을 명시하므로 실행 정책에는 영향이 없다.
- 판단: 기존 호환성 실패와 더 넓은 승인 가드 강화는 이번 비용 개선 범위 밖으로 유지했다. 기존 실패가 남는 위험과 실제 호스트 대화 미검증 범위를 위에 공개한다.
- 판단: 미커밋 호환성 변경을 포함하는 현 체크아웃에서 작업했다. 의존성/오프라인·분석 백엔드를 유지하며 추가 릴리스·설치는 하지 않았다.
