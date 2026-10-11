# 호환성 수정·검증 기록 — 0.35.1

검증일: 2026-10-08. 기준은 [0.35.0 감사](compatibility-audit.md), main `4c9acea`와 기존 미커밋 가이드다. 수정본은 `fix/compatibility-0.35.1`의 로컬 패키지이며 원격 main·공개 릴리스로 게시했다고 보고하지 않는다.

116개 추적 파일의 구조·호출·입출력 계약을 읽은 감사 inventory와 공식 source ledger를 재사용하고, 변경된 소스·공식 문서를 추가 확인했다. 구현 순서는 빌드/재개 → AST → 스펙 → 런타임/호스트 → 예제/버전 → 문서/실행 검증이다. 자체 `tests/` 소스 15개의 감사 시점 SHA-256은 모두 동일하며 추가·수정·삭제하지 않았다.

## 구현 범위

| 감사 ID | 적용한 수정 | 확인 근거·제한 |
|---|---|---|
| F01–03 | Maven parent/BOM/properties와 effective POM, Gradle 실제 configuration, 주석 제외, 활성 JaCoCo goals/skip/XML/phase 확인 | 기존 경계 관찰과 실제 빌드. 비활성 phase=none은 capability false. 미확정 값은 partial/질문 |
| F04–06, F09–10 | 깊은 모듈 소스·모듈별 리포트, 명시 report_dirs/report_paths/aggregate_report, 전체 stdout의 configuration 출력 사용 | 실제 Gradle 하위 service 모듈 실행·게이트 성공. 확인되지 않은 aggregate·누락 모듈은 partial |
| F07 | 승인된 SC ID와 테스트 scenarioRef 연결, pending·누락 매핑 시 재개 하향 | pending은 생성 단계 이후로 진행하지 않음. 폴더/INDEX만 있는 기존 테스트는 생성 출처로 인정하지 않음 |
| F08 | 실제 클래스·다른 측정 카운터가 있는 branchless XML의 BRANCH는 N/A | 유효한 synthetic class XML로 gate ok/pass true. 측정 없는 XML은 성공 근거 아님 |
| F11–13 | Java CLI stdout·파싱 UTF-8, 최소 JVM17, 실제 language level 전달·파싱 진단 | 실제 JVM 한글 분석, record의 source11 partial / source17 ok. 기본 CURRENT(26)은 확인된 프로젝트 source level을 대신하지 않음 |
| F14–18 | record/enum/중첩 타입, file/fields/methods, 미해결 타입, publicMethods, 오버로드 signature별 호출 및 legacy 합집합 | 기존 AST 관찰·검사. 파싱/미해결 의미는 생성 성공으로 간주하지 않음 |
| F19–20 | 확인된 sourceRoots/classpath 컨텍스트와 범위 제한, 정확한 FQCN | SDK의 a.Service 조회에 다른 패키지 Service 미포함. 모든 dependency/generated source 의미를 자동 확정하지 않음 |
| F21–24 | Java8 Collections, compiler3.10.1 source/target8, Boot4 슬라이스 package/starter, JaCoCo0.8.15 | 공식 문서 대조. 0.8.15는 JDK17의 실제 Maven 테스트·계측 확인; JDK8/26·Boot4 전체 실행은 미실행 |
| F25–28 | 모든 문서 한 번에 인덱싱, 마스킹 원문에서 기준 추출, 미지원 형식·엄격 UTF-8/BOM·한도·읽기 오류 | CP949 거부/BOM 허용, overlap 재합성 제거, 뒤늦은 인덱싱 publish 거부. PDF/YAML/DOCX는 변환 필요 |
| F29–31 | 수동 --data 전달, 실제 선택한 JDT Java 검사, 검증 Python+jdtls.py --java-executable | 소스·공식 구현 대조. 실제 Claude JDT initialize 세션은 미실행 |
| F32–34 | CRC/SHA/소스 지문·원자 manifest·쓰기 잠금, immutable jar 유지, 소유 프로세스 트리 종료, 설치 로그 stderr | copy 실패 시 이전 jar 유지, 손상 jar 최신 판정 거부, 실제 timeout 후 손자 프로세스 없음. 실제 uv cold 설치는 미실행 |
| F35–38 | Windows 경로·basename·Zone C 대소문자, UTF-8 상태줄, delegate 셸/설정 보존, PEP440 버전 검사 | 대소문자 SC/RA 경로도 가드 거부; SDK2.3.0+vendor.1/2.3 허용. 실제 Claude 상태줄 UI는 미실행 |
| F39–41 | dependency BOM과 pluginManagement 구분, Boot2.2/2.3 Vintage 설명, 구형 Gradle XML DSL 분기 | 공식 문서·예제 대조. 구형 Gradle/JDK8 실제 실행은 미실행 |
| F42 | DATA 실제 경로·쓰기 가능 힌트·긴 경로 진단, 공식 호스트 설정의 짧은 경로 안내 | 격리된 짧은 CODEX_HOME에서 warm 연결. Windows 긴 경로 문제를 모든 환경에서 해소했다고 주장하지 않음 |
| F43 | 한글 Maven agent 데이터 경로 위험·조건부 설정 제안 | 실제 agent jar·JVM args·workingDirectory를 확인한 검증용 POM만 변경. 한글·공백 경로/JDK17/Maven3.9.9/JaCoCo0.8.15에서 JUnit2개+exec/XML+게이트 확인 |

기존 MCP 이름과 도구 수 **repo-ast 5 / spec-doc 4 / build-test 11**, `schemaVersion:2`, Claude의 root 생략, 기본 오프라인 정책을 유지한다. 선택적 java_home·보고서·분석 context 인자를 추가했다. Codex는 LSP·상태줄·강제 훅 없이 `lspAvailable:false`로 동작한다. 상세 계약은 [compatibility-runtime.md](../references/compatibility-runtime.md)에 있다.

## 추가 위험 C01–C10의 처리

- **C01**: 소스·리소스·빌드·스펙·설정 SHA-256과 보고서 지문을 기록한다. 동일 mtime 빌드 변경은 0단계, 리소스 추가는 6단계로 재진입했다. SC의 매핑/검증 결과 절만 덧붙이는 경우는 시나리오 내용 변경으로 처리하지 않는다. 커스텀 소스·스펙 경로는 실제 설정과 영향 파일을 별도로 확인한다.
- **C02–03**: 실제 configuration/effective POM으로 근거를 보완하며 미확정·지원 밖 Boot는 partial/interviewRequired다. 분석용 JDK17, Claude JDT JDK21, 빌드 java_home은 분리한다. 지원 조합 전체를 실행하지는 않았다.
- **C04–05**: 설치 대기/작업 종료 시간을 제한하고 살아 있는 lock owner를 존중한다. 스펙 인덱스는 한 프로세스 한 root이며 최신 요청만 publish한다. 늦은 요청의 덮어쓰기를 경계에서 확인했으며 실제 호스트 취소 메시지의 전체 경로는 미검증이다.
- **C06–07**: 지원 텍스트·UTF-8·크기/파일 한도·범위 이탈·읽기 오류를 명시한다. standalone wheel은 MCP 모듈만 포함하며 전체 플러그인 설치를 대신하지 않는다. 대용량·권한·junction 모든 조합을 검증하지 않았다.
- **C08–09**: Maven report를 verify 단계로 옮겨 앞선 integration-test 데이터를 포함하도록 했다. 별도 IT exec 파일이면 합산 경로를 실제 확인한다. MVC 보안 해제를 가정하는 property를 제거하고 실제 인증 정책을 사용하도록 예제를 수정했다. Boot4 Security/Jackson3 slice의 실제 컨텍스트 실행은 미검증이다.
- **C10**: 아래 실행/미실행 표를 유지한다. cmd metacharacter·UNC·Store alias·ARM·권한 없는 DATA·proxy 등 미실행 조건을 성공으로 추정하지 않는다.

## 실제 실행 결과

환경: Windows11, Python3.14.0, MCP2.3.0, packaging26.3(허용 >=26.1,<27), Node24.12.0, JDK17.0.7, Maven3.9.9, Gradle8.12, Codex CLI/app-server0.162.0-alpha.2. 새 테스트 스위트를 만들지 않고 기존 검사/통합 runner와 ignored 검증 자료를 사용했다.

| 검증 | 결과 |
|---|---|
| 기존 integration/verify_real_builds.py | exit0. Boot3.2/JaCoCo0.8.12의 기존 fixture 그대로 Gradle·Maven 각각 일반/한글 메서드/IT·skip·패턴 불일치·컴파일 실패·보정·커버리지 범위 확인 |
| JaCoCo0.8.15 별도 실제 실행 | ASCII Maven/JDK17 JUnit2개 성공. 한글·공백 Maven은 확인된 상대 destfile 적용 후2개 성공, 최신 실행 데이터·XML·게이트 확인 |
| Gradle aggregator 기본 test | root에 테스트 없이 service 하위 모듈만 있는 실제 빌드에서2개 성공, 보고서·실행 데이터·게이트 확인 |
| AST CLI offline package | exit0. JavaParser3.28.2/release17 유지 |
| Python compileall / Node --check / git diff --check | 오류 없음. Git의 LF/CRLF 안내는 별도 |
| 로컬 Codex0.35.1 설치·활성화 | 격리된 CODEX_HOME에서 installed/enabled 확인; 마지막 소스를 재설치한 캐시 사용 |
| Codex app-server | skills/list에서15개, mcpServerStatus/list에서11/5/4개, RPC 오류 없음. 첫 cold SDK 준비 때30초 handshake 실패가 있었으며 준비 후 warm 연결 성공 |
| 실제 Node→bootstrap→MCP stdio | Codex 명시 절대 root와 Claude 생략 root 모두3서버 health·20개 도구 확인. 동일 AST는 미해결 Spring 심볼을 양쪽 모두 partial로 보고, 스펙/JUnit 해석은 ok |
| JavaParser 영속화 | 설치본 수동 --data 실행 status ok, integrityVerified/upToDate true. 로컬 설치가 target jar도 복사한 경우 jarPath는 그 사본을 우선하며 DATA 무결성은 별도로 확인 |
| 경계·최신성 | 누락 root·루트 밖 입력·다른 스펙 root 거부, 유효 branchless, pending 승인, 동일 mtime 빌드 변경, 리소스 변경, 결과 절 추가 후 재개 확인 |
| 프로세스·스펙 경합 | 실제2초 timeout 후 소유 손자 프로세스 없음. 뒤늦은 index는 SPEC_DOC_INDEX_SUPERSEDED이며 새 원문 스냅샷 유지 |

실행 자료는 저장소의 ignored `_workspace/compatibility-fix/`에 남겼다: `real-builds2/results.json`, `live-0351-results.json`, `final-probes-results.json`, `app-results.json`, `codex-installed.json`, `stdio-0351-results.json`, `installed-persist.json`, 기존 검사·빌드 로그. 이것들은 배포 스킬이나 새로운 플러그인 테스트 스위트가 아니다.

## 기존 검사에서 남은 실패

최종 명령은 UTF-8 환경의 `python -m unittest discover -s test-autoevermation-harness-plugin/tests -p 'test_*.py'`다. **197개 실행, 실패 이벤트16·오류4·skip3이며 전체 통과가 아니다.** subTest 실패가 포함되므로 실패 이벤트 수를 독립 테스트 개수나 통과 개수로 환산하지 않는다. 감사 전 baseline은 실패1·오류3·skip3이었다.

| 분류 | 남은 검사·원인 |
|---|---|
| 기존 Windows/검사 결함 | test_build_contract_v2의 `server` NameError, `/integrationTest/` 구분자 가정, test_pipeline_v2 symlink2개의 WinError1314, POSIX stdio3개 skip |
| 내부 구현 mock | timeout 검사는 subprocess.run을 patch하지만 실제 timeout/취소 정리를 위해 Popen을 사용한다. bootstrap Windows 검사는 가짜 `/usr/bin/python3`와 subprocess.run 호출 자체를 가정한다. 실제 stdio/timeout은 위의 별도 실행으로 확인 |
| 승인·출처·최신성 강화 | INDEX/폴더만 있고 승인 SC+scenarioRef/실행 지문이 없는 fixture의 이전 단계5/6/8/9 기대와 현재 보수적 결과가 다름. test_env_and_staleness2개, test_mutation_removal StaleReport1개, test_pipeline_state_contract8개 subTest/검사 실패 이벤트 |
| capability/aggregate/API 계약 | prepare-agent만 있는 Maven을 XML 가능으로 보던 fixture, 확인 없는 root aggregate 우선 가정, public signature를 인자 목록 그대로 비교하는 검사. 이번 선택 인자와 엄격한 설정·범위 판정이 기존 기대와 다름 |

사용자가 자체 테스트 소스 변경을 금지했으므로 기대값을 수정하거나 검사를 삭제·skip하여 녹색으로 만들지 않았다. 이 상태를 공개 릴리스 전 전체 회귀 검사 통과로 표현하지 않는다.

## 최종 리뷰와 적용 결정

별도 컨텍스트의 전체 변경 리뷰를 한 번 수행했다. Critical은 없었고 Important5개를 실제 경계 재현과 대조해 수정했다.

1. 실패 빌드의 exitCode·timedOut을 재개 지문 확인에 포함하고 실행 시작부터 이전 증거를 무효화했다. 실패/timeout 증거는 RUN_NOT_SUCCESSFUL로 거부한다.
2. Gradle의 unqualified test 선택을 하위 모듈까지 적용하여 JUnit·JaCoCo·exec 범위를 맞췄다. 실제 aggregator 실행으로 확인했다.
3. Maven phase=none 등 실행하지 않는 바인딩을 capability에서 제외했다. 기본 goal binding은 유지했다.
4. Surefire/Failsafe execution-level argLine/workingDirectory가 있으면 자동 change 없이 확인을 요구한다. late-bound property의 기존 JVM args를 보존한다.
5. Windows Zone C와 workspace segment의 대소문자 비교를 일치시켰다. SC·RA 변형 경로도 동일하게 차단했다.

지원 밖 Boot의 null 프로파일을 partial로 처리하고 중복 import·jar 설명도 정리했다. 판단 범위 밖으로 남긴 것은 실제 Claude 훅/상태줄/JDT, host-driven 취소·cold 설치 전체, 비공개 SDK 배포, 모든 classpath 의미, Boot/JDK/OS 행렬, 실제 GUI/모델 파이프라인이다. 문서 작성 중인 완성도는 저자가 최종 링크·버전·내용으로 확인했다.

적용 결정: 기존 dirty 문서를 보존하기 위해 현재 checkout의 별도 fix 브랜치를 사용했다. 테스트 금지·기존 승인 규칙을 우선하여 의무 TDD/새 메타 suite/중복 승인을 추가하지 않았다. 승인된 최소 핀 갱신만 적용했다. Unicode Maven은 전체 JVM 옵션을 덮어쓰지 않고 실제 확인한 조건의 검증용 POM에 한정했다. 이 결정들의 한계는 전체 회귀 검사 미통과·미실행 행렬이며 위 표에 공개한다.

## 남은 검증 범위

실제 Codex 데스크톱 GUI 설치 클릭, 모델의 승인→생성→실패 보정→커버리지 보완→시나리오 불일치 보정 전체 대화, Claude 버전별 훅/LSP initialize·상태줄, macOS/Linux/ARM, JDK8·21·24–26/Boot2·3.4+·4 기술별 테스트는 미실행이다. 실제 사용자 프로젝트의 resolved dependency/소스셋/보안·프록시/빌드 configuration은 사용 시 다시 확인한다. 지원 선언은 공식 계약에 따른 범위이며 모든 조합 실행 통과를 의미하지 않는다.

공식 근거: [OpenAI 패키징](https://developers.openai.com/plugins/build/plugins), [MCP SDK2 migration](https://py.sdk.modelcontextprotocol.io/migration/), [Gradle task 선택](https://docs.gradle.org/current/userguide/command_line_interface.html#sec:executing_tasks_in_multi_project_builds), [Gradle JaCoCo](https://docs.gradle.org/current/userguide/jacoco_plugin.html), [Maven lifecycle](https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html), [JaCoCo release](https://www.jacoco.org/jacoco/trunk/doc/changes.html)·[agent](https://www.jacoco.org/jacoco/trunk/doc/agent.html), [Boot4 migration](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide), [JavaParser3.28.2 ParserConfiguration](https://github.com/javaparser/javaparser/blob/javaparser-parent-3.28.2/javaparser-core/src/main/java/com/github/javaparser/ParserConfiguration.java). 파일·심볼·확인 버전과 적용 결정은 [RESEARCH_NOTES](../RESEARCH_NOTES.md)에 연결한다.
