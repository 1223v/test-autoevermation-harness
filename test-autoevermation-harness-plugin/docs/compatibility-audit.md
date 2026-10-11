# 하네스 호환성·오류 감사 — 0.35.0

> 이 문서는 0.35.0 감사 시점의 원인·재현 기록이다. 0.35.1의 대응과 최신 검증은 [호환성 수정 기록](compatibility-remediation.md)을 참고한다. 아래의 과거 결과를 수정 후 통과로 바꾸지 않는다.

조사일: 2026-10-08. 기준 커밋: `4c9acea`. 조사 시작 시 존재한 문서 5개의 미커밋 변경도 읽었으며 그대로 보존했다. 이번 감사는 오류 식별·보고 작업이다. 구현, 의존성, 매니페스트, 플러그인 자체 테스트 파일은 변경하지 않았다.

가장 먼저 해결할 문제는 **잘못된 버전 선택, 모듈별 커버리지·최신성 누락, 불충분한 승인 증거에 따른 재개 추천, AST의 오류·타입 정보 누락**이다. 이들은 실패를 표시하는 것뿐 아니라 정상·완료에 가까운 상태를 잘못 보고할 수 있다. Boot 4 템플릿과 Windows/JDK 17 한글 AST 출력도 일반적인 사용을 막는 조건이다.

## 1. 범위·증거·프로젝트 구조

대상은 선언된 Spring Boot 2.0–4.x, Java 8–26, Gradle 5.x–9.x/Maven 3.6.3+, Codex 앱·CLI/Claude Code, Windows/macOS/Linux다. 각 축의 모든 조합이 공식 지원되는 것은 아니다. Boot·Gradle 실행 JVM·테스트 JVM·바이트코드 처리 도구의 호환 교집합을 적용해야 한다.

현재 직접 확인한 환경은 Windows, Python 3.14.0, MCP SDK 2.3.0, Node 24.12.0, Oracle JDK 17.0.7이다. 기존 실제 빌드 자료는 Gradle 8.12/Maven 3.9.9, Boot 3.2.0/Jupiter/JaCoCo 0.8.12를 사용한다. 다른 환경을 이 결과로 통과 처리하지 않았다.

증거는 다음처럼 구분한다.

- **재현:** 현재 코드에 최소 입력을 전달하거나 실제 JVM/SDK로 현상을 관찰했다. mock·합성 XML·함수 경계인 경우 해당 제한을 적었다.
- **정적 확인:** 현재 코드·문서와 해당 버전의 공식 계약이 충돌한다. 전체 호스트 실행은 아직 확인하지 않았다.
- **기존 실행:** 저장소의 이전 원시 실행 자료·검증 기록을 재사용했다. 이번 감사의 새 실행과 구분한다.
- **추가 확인:** 가능한 위험 조건이지만 실제 결함으로 확정하지 않았다.

P1은 일반적인 생성·분석을 막거나 잘못된 성공/재개를 보고하는 문제, P2는 특정 환경·구성의 실패 또는 분석 제약, P3는 제한적인 배포·문서 문제다. 발생 확률의 임의 수치는 사용하지 않는다.

확인된 문제·제약은 **43건(P1 19건, P2 22건, P3 2건)**이다. 증거의 주된 분류는 재현 30건(실제 JVM/SDK·직접 호출·mock 경계·직전 관찰 포함), 정적 확인 11건, 기존 실행 2건이며 각 항목에 실제 범위를 적었다. 추가 확인 후보 10건은 이 수에 포함하지 않는다.

### 전체 구조 점검표

116개 추적 텍스트 파일을 모두 읽어 경로·행 수·SHA256·구조 앵커를 기록했다. 파일 읽기와 실제 행동 검증은 구분한다. 상세 목록은 로컬 감사 증거의 `inventory.json`에 있다.

| 영역 | 파일 수 | 확인한 책임·계약 | 관련 항목 |
|---|---:|---|---|
| 루트·마켓플레이스·개발 지침 | 5 | 두 호스트 배포, 지원 선언, 수정 제한 | §4, §5 |
| 플러그인 루트·Claude 매니페스트 | 11 | 버전, portable/Claude MCP, LSP, 설정·의존성·연구 | F22–24, F29, F39–43 |
| MCP·Java CLI·래퍼 | 15 | bootstrap, 경로, 분석, 인덱스, 실행, 리포트·재개 | F01–20, F25–28, F32–34, F38 |
| 역할 문서 | 11 | 입력/출력, 소스 의미, 시나리오, 생성·보정·적합성 | F09, F15–16, F22, F25, F27 |
| 스킬·오케스트레이션 참조 | 16 | 15개 스킬과 공용 단계·승인·호스트 분기 | F07, F22, F27, F29, §4 |
| 참조 정책 | 13 | 버전, 환경, fallback, 결과·시나리오 계약 | F21–24, F29–31, F39–41 |
| 훅 | 2 | SessionStart, 위임·산출물 가드, 상태줄 설치 | F29, F35–37 |
| 스크립트 | 9 | 영속 jar/JDT, 가드·타이밍·상태줄·redaction | F29–37 |
| 예제 | 13 | 두 빌드 도구, Boot 2/4, JUnit, JSON, CI | F21–24, F39, F41, C08–09 |
| 기존 문서 | 6 | 설치·업데이트·운영·검증·도구 제한 | F42–43, §4–5 |
| 기존 검사·통합 runner | 15 | 정상/오류 계약의 현재 검증 범위 | §5 |

호출 흐름은 호스트의 스킬 선택 → 호스트 어댑터 → 설정·환경 확인 → 스펙/AST/소스 분석 → 시나리오 승인 → 생성 → JUnit 실행·보정 → JaCoCo → 적합성 → 집계·재개다. MCP 런처는 Node → Python bootstrap → 세 서버이며, repo-ast는 Java CLI를 추가 실행한다. Claude의 LSP·훅·전역 상태줄은 별도 경로다.

## 2. 확인된 문제·제약

각 권고는 후속 수정의 최소 방향이다. 이번 감사에서 적용하지 않았다. `boundary-results.json`은 직접 호출·합성 입력, `ast-results.json`은 실제 JVM, `sdk-results.json`은 SDK in-process 결과다. 직전 조사에서 재사용한 협업 관찰은 `prior-observations.json`에 출처와 제한을 남겼다.

### F01 — Maven placeholder를 다른 의존성 버전으로 판정 [P1 / 재현]

위치: [build_test_server.py:614](../mcp/build_test_server.py#L614), `_BOOT_MAVEN_PARENT_RE`, `_detect_boot_version`.

Boot parent `${boot.version}`와 실제 property `2.7.18`, 뒤쪽 JUnit `4.13.2`를 넣으면 Boot **4.13.2 / jakarta / Java 17 / MockitoBean**을 `degraded:false`로 반환한다. DOTALL 정규식이 parent 밖의 version까지 소비한다. 증거: `maven-placeholder-version`. 생성 프로파일 전체가 잘못 바뀐다. [Maven POM 계약](https://maven.apache.org/pom.html).

최소 권고: XML 노드 경계를 지키고 property/BOM/parent 증거를 해석한다. 확인할 수 없으면 미확정으로 질문한다. 우회: 실제 Boot 버전을 확인하여 config를 명시하고 자동 감지 결과와 대조한다.

### F02 — Gradle 주석을 실행 설정으로 읽음 [P1 / 재현]

위치: [build_test_server.py:633](../mcp/build_test_server.py#L633), `_detect_boot_version`; [동일 파일:1580](../mcp/build_test_server.py#L1580), `_gradle_capabilities`.

주석의 Boot 2.7.18 뒤 실제 Boot 4.1.0을 선언해도 2.7.18을 선택한다. `java` 플러그인만 활성화하고 주석에 `id "jacoco"`, `xml.required=true`를 적으면 JaCoCo 준비 완료다. 증거: `gradle-comment-version`, `gradle-comment-capabilities`.

최소 권고: 주석/문자열과 활성 DSL 구성을 분리하고 설정 단계의 실제 역량으로 검증한다. 우회: 감지 값과 실제 빌드 출력을 확인한다.

### F03 — Maven pluginManagement를 활성 JaCoCo로 판정 [P1 / 재현]

위치: [build_test_server.py:1616](../mcp/build_test_server.py#L1616), `_maven_capabilities`.

`build/pluginManagement`에 report goal만 넣어도 `jacoco:true`, `jacocoXml:true`, `missing:[]`다. 실제 활성화·prepare-agent binding을 증명하지 못한다. 증거: `maven-management-capabilities`. [공식 pluginManagement 의미](https://maven.apache.org/pom.html).

최소 권고: 활성 plugin/execution을 확인하고 상속·profile은 effective POM 증거로 판단한다. 우회: 실제 테스트 JVM agent와 최종 XML 생성을 확인한다.

### F04 — 일반 루트 JaCoCo 리포트가 하위 모듈을 숨김 [P1 / 재현]

위치: [build_test_server.py:190](../mcp/build_test_server.py#L190), `_find_reports`; [동일 파일:407](../mcp/build_test_server.py#L407), `_find_jacoco_xml_all`.

루트의 일반 `target/site/jacoco/jacoco.xml`은 100%, 하위 service 리포트는 0%인데 루트만 선택하여 `pass:true`다. 루트 리포트를 항상 aggregate로 가정하며, 기본 경로에서 하나라도 찾으면 깊은 재귀 fallback도 생략한다. 증거: `root-report-hides-child`. 공식 aggregate 기본 위치는 [jacoco-aggregate](https://www.jacoco.org/jacoco/trunk/doc/report-aggregate-mojo.html)다.

최소 권고: 실제 집계 여부·대상 모듈을 확인하고 누락 모듈도 보고한다. 우회: 모듈별 root로 검사하거나 확인된 aggregate를 사용한다. 검증된 aggregate와 개별 보고서를 단순 합산하면 중복 계산되므로 피한다.

### F05 — 깊은 모듈의 소스 변경을 최신성 검사에서 누락 [P1 / 재현]

위치: [build_test_server.py:228](../mcp/build_test_server.py#L228), `_SOURCE_REL`, `_collect_source_files`.

`services/orders/src/main/java` 소스 mtime 500, JUnit mtime 100에서 소스 목록이 비고 `sourceNewerThanJunit:false`다. root와 한 단계 submodule만 찾는다. 증거: `deep-module-freshness`.

최소 권고: 실제 모듈/source set을 기준으로 변경 증거를 수집한다. 우회: 해당 모듈을 root로 지정하고 관련 단계를 재실행한다.

### F06 — 무관한 최신 리포트가 오래된 모듈 결과를 가림 [P1 / 재현]

위치: [build_test_server.py:284](../mcp/build_test_server.py#L284), `_compute_staleness`.

service 소스 200·service JUnit 100·다른 모듈 JUnit 300이면 전역 최대 mtime 비교로 stale=false다. 증거: `unrelated-report-masks-stale`.

최소 권고: 실행 대상·모듈·소스와 대응하는 리포트의 최신성을 확인한다. 우회: 변경 대상의 JUnit·JaCoCo를 다시 실행하고 명시적으로 대조한다.

### F07 — 승인 없는 시나리오도 뒤 단계 재개를 추천 [P1 / 재현]

위치: [build_test_server.py:1386](../mcp/build_test_server.py#L1386), `detect_pipeline_state`의 provenance/stage inference.

기존 테스트·pending 시나리오 1개·green JUnit·100% JaCoCo만 있으면 `approved:0`, `harnessProvenance:true`, `recommendedEntryStage:9`다. 증거: `pending-scenario-resume`. 시나리오 파일 존재를 생성 provenance로 인정한다. **이 결과는 잘못된 MCP 추천의 증거이며 실제 호스트의 승인 우회를 증명하지 않는다.** Codex 어댑터는 현재 승인 재확인을 지시한다.

최소 권고: 현재 대상의 승인·테스트 연결을 재개 선행 조건으로 확인한다. 우회: 추천 단계와 무관하게 승인 범위를 확인하고 부족하면 설계/승인 단계로 돌아간다.

### F08 — 분기 없는 정상 JaCoCo XML을 실패 처리 [P2 / 재현]

위치: [build_test_server.py:1528](../mcp/build_test_server.py#L1528), `coverage_gate`.

LINE/METHOD/CLASS가 모두 100%이고 BRANCH가 없는 XML은 `partial`, `pass:false`, uncovered=[]다. JaCoCo 0.8.12 [XML writer](https://raw.githubusercontent.com/jacoco/jacoco/v0.8.12/org.jacoco.report/src/org/jacoco/report/internal/xml/XMLCoverageWriter.java)는 total=0 카운터를 생략한다. 증거: `branchless-gate`.

최소 권고: 해당 없음과 리포트 불완전을 구별하는 정책을 명시한다. 정상 분기 없는 코드에 분기를 추가하는 우회는 권하지 않는다. 실제 straight-line 프로젝트 생성부터의 전체 실행은 미검증이다.

### F09 — 사용자 지정 JUnit 리포트 위치를 찾지 못함 [P2 / 재현]

위치: [build_test_server.py:206](../mcp/build_test_server.py#L206), `_find_junit_xml`; [동일 파일:1061](../mcp/build_test_server.py#L1061), `_task_junit_xml`; [test-runner:55](../agents/test-runner.md#L55), `reportDir` 계약.

정상 XML을 `artifacts/junit/TEST-demo.xml`에 두면 task 지정·일반 parse 모두 failed/리포트 0개다. 역할 입력은 reportDir을 받지만 MCP에는 전달 인터페이스가 없다. [Gradle 공식 JUnit 경로 설정](https://docs.gradle.org/current/userguide/java_testing.html). 증거: `custom-junit-task-path`; 실제 Gradle custom-output 빌드는 미실행이다.

최소 권고: 역할 입력과 MCP의 실제 경로 계약을 일치시킨다. 우회: 검증 범위에서 기본 출력 경로를 사용하고 오래된 파일을 새 결과로 복사하여 위장하지 않는다.

### F10 — 긴 Gradle 로그에서 task 발견 결과를 잃음 [P2 / 재현: 함수 경계]

위치: [build_test_server.py:724](../mcp/build_test_server.py#L724), `_output_tail`; [동일 파일:945](../mcp/build_test_server.py#L945), `list_test_tasks`.

task marker 뒤 4,000자보다 긴 설정 출력이 있으면 stdoutTail에서 marker가 사라지고 `tasks:[]`, `configurationVerified:true`, status=ok다. 실제 trimming 함수와 mocked subprocess 반환을 사용했다. 증거: `task-log-tail`; 실제 대형 Gradle 프로젝트 실행은 미검증이다.

최소 권고: 구조화 marker는 전체 출력에서 수집하고 표시용 tail과 분리한다. 우회: 실제 task 목록과 비교한다. 관련 기존 검사도 NameError로 이 조건을 제대로 확인하지 못한다(§5).

### F11 — Windows/JDK 17 한글 Java 출력에서 AST 호출 예외 [P1 / 재현: 실제 JVM]

위치: [repo_ast_server.py:337](../mcp/repo_ast_server.py#L337), `_run_java_cli`; [AstCli.java:67](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L67); [launch.cjs:36](../mcp/launch.cjs#L36).

UTF-8 Python과 JDK 17.0.7/CP949 출력의 조합에서 `sc001_거래`는 reader thread의 UnicodeDecodeError를 거쳐 `None.strip()` AttributeError가 된다. 증거: `ast-results.json`의 Korean.java, `ast-probe.log`. [OpenJDK 17.0.7 stdout](https://raw.githubusercontent.com/openjdk/jdk17u/jdk-17.0.7-ga/src/java.base/share/classes/java/lang/System.java), [Python subprocess 계약](https://docs.python.org/3.14/library/subprocess.html).

최소 권고: Java JSON 출력과 Python decoding의 인코딩 계약을 명시하고 프로세스/디코딩 실패를 구조화한다. 우회: 분석 JVM의 UTF-8 출력을 확인한다. JDK 21·다른 OS에서도 같은 예외가 난다고 주장하지 않는다.

### F12 — Java 최소 버전 검사가 실제 CLI 요구와 다름 [P2 / 재현: 함수 경계]

위치: [repo_ast_server.py:285](../mcp/repo_ast_server.py#L285), `_jdk_available`; [CLI pom:20](../mcp/javaparser-cli/pom.xml#L20), release 17.

`java -version` 성공 코드와 Java 8 출력을 mocked하면 available=true다. 실제 Java major를 판정하지 않아 CLI release 17 실행 역량을 증명할 수 없다. 증거: `jdk8-health-function-boundary`. 현재 감사에서 실제 JDK 8 Maven/CLI 실행은 하지 않았다.

최소 권고: 실행할 Java의 경로·major를 함께 검증한다. 우회: health boolean 외에 실제 CLI JVM을 확인한다.

### F13 — Java 언어 수준·파싱 문제를 정상 분석으로 보고 [P1 / 재현: 실제 JVM]

위치: [AstCli.java:88](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L88), ParserConfiguration; [동일 파일:102](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L102), ParseResult 처리.

JavaParser 3.28.2의 [기본 language level](https://raw.githubusercontent.com/javaparser/javaparser/javaparser-parent-3.28.2/javaparser-core/src/main/java/com/github/javaparser/ParserConfiguration.java)은 Java 11이다. `getResult()`만 사용하여 parse problems를 놓친다. 잘못된 소스는 targets=0·errors=[]·status=ok, Java 17 text block은 String까지 unresolved다. 증거: Broken.java, TextBlock.java.

최소 권고: 실제 source/release와 언어 수준을 맞추고 ParseResult 성공 여부·문제를 전달한다. 우회: 컴파일 진단을 병행하고 비어 있는 분석을 성공 근거로 사용하지 않는다.

### F14 — record·enum·중첩 클래스 누락 [P2 / 재현 및 정적 확인]

위치: [AstCli.java:121](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L121), 최상위 ClassOrInterfaceDeclaration 필터.

public 메서드가 있는 Java 17 record는 target=0·status=ok, 중첩 public class의 메서드는 외부 클래스 결과에서 사라진다. enum도 같은 필터에서 제외된다(정적 확인). 증거: RecordDto.java, Nested.java. JavaParser 3.28.2는 별도 [타입 노드](https://github.com/javaparser/javaparser/tree/javaparser-parent-3.28.2/javaparser-core/src/main/java/com/github/javaparser/ast/body)를 제공한다.

최소 권고: 대상 타입 범위를 지원하거나 누락을 명시한다. 우회: 해당 소스·중첩 테스트를 직접 확인하고 미분석 대상을 충족으로 처리하지 않는다.

### F15 — AST MCP가 file·fields 계약을 누락 [P1 / 재현]

위치: [repo_ast_server.py:657](../mcp/repo_ast_server.py#L657), `_build_result`; [AST 역할:59](../agents/ast-structure-analyzer.md#L59); [적합성 역할:78](../agents/scenario-conformance-verifier.md#L78).

CLI가 만든 fields와 Python 정규화 단계의 file을 MCP testTarget이 전달하지 않는다. 역할 스키마가 요구하는 클래스별 file·fields가 없다. receiver=`paymentClient`가 있어도 필드 타입과 결합할 수 없고, 적합성의 단순 메서드명 fallback으로 다른 협력 객체의 같은 이름 호출을 구별하기 어렵다. 보정 파일 라우팅에도 영향이 있다. 증거: Receiver.java. 실제 전체 적합성 세션의 오판은 미실행이다.

최소 권고: 기존 역할 스키마에 맞는 필드·파일 정보를 보존한다. 우회: 소스로 receiver 타입과 파일을 확인하고 불명확한 경우 보류한다.

### F16 — 미해결 매개변수·필드 타입을 보고하지 않음 [P1 / 재현]

위치: [AstCli.java:178](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L178), 반환 타입만 resolve.

MissingField·MissingParam이 정의되지 않아도 `unresolvedSymbols:[]`, status=ok이며 public signature에 MissingParam을 남긴다. 상속·애노테이션 타입도 해결 실패 수집이 불충분하다(정적 확인). 증거: Basic.java.

최소 권고: 생성 판단에 필요한 타입 위치의 해결 상태를 보고한다. 우회: 실제 컴파일과 정의 소스를 확인하고 불명확한 의미를 추측하지 않는다.

### F17 — private 메서드를 publicMethods에 포함 [P2 / 재현]

위치: [repo_ast_server.py:534](../mcp/repo_ast_server.py#L534), `_public_methods`.

CLI의 public flag를 검사하지 않아 private hidden()이 publicMethods에 들어간다. 그대로 생성 후보로 쓰면 접근 불가 호출을 만들 수 있다. 증거: Basic.java.

최소 권고: visibility를 반영한다. 우회: 소스의 접근 제한자를 확인한다.

### F18 — 오버로드의 호출 정보 덮어쓰기 [P2 / 재현]

위치: [repo_ast_server.py:545](../mcp/repo_ast_server.py#L545), `_method_calls`; [동일 파일:560](../mcp/repo_ast_server.py#L560), `_method_call_details`.

same()의 gc 호출과 same(int)의 exit 호출 중 마지막만 methodCalls.same에 남는다. signature 목록은 둘 다 있어 결과가 불일치한다. 증거: Basic.java.

최소 권고: 이름과 시그니처를 함께 식별한다. 우회: 오버로드별 소스를 읽어 호출을 확인한다.

### F19 — 외부 클래스패스·여러 소스 루트 해결 제약 [P2 / 재현: 분석 제약]

위치: [AstCli.java:83](../mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java#L83), CombinedTypeSolver; `inferSourceRoot`.

JRE와 한 inferred source root만 보며 외부 JAR·형제 모듈·test/generated roots를 등록하지 않는다. ResponseEntity<String>은 unresolved/partial이다. 증거: External.java. 이 상태는 Codex 어댑터에도 명시된 제약이며 그 자체를 잘못된 status=ok로 보고한 사례는 아니다.

최소 권고: 실제 classpath/source roots를 확보하는 경로를 마련하거나 보류 정책을 구체화한다. 우회: 소스·컴파일 증거를 병행한다. 해결되지 않은 필수 대상은 보류한다.

### F20 — FQCN 조회에 다른 패키지의 같은 이름을 포함 [P2 / 재현: SDK]

위치: [repo_ast_server.py:986](../mcp/repo_ast_server.py#L986), `resolve_symbol`.

a.Service 조회가 a.Service와 b.Service 둘 다 반환하며 status=ok다. FQCN 비교 뒤 단순 이름 OR 조건도 적용한다. 증거: `sdk-results.json`의 fqcn-resolution, 실제 SDK 2.3.0 in-process 호출.

최소 권고: FQCN과 단순 이름 질의를 구별한다. 우회: paths를 좁히고 반환 FQCN을 확인한다.

### F21 — Java 8 생성 예제의 List.of [P1 / 재현: 컴파일]

위치: [JUnit4 예제:35](../examples/java/OrderControllerTest_boot2_junit4.java#L35), [Jupiter 예제:33](../examples/java/OrderControllerTest_boot2_jupiter.java#L33), [버전 참조:117](../references/version-compatibility.md#L117).

Java 8 프로파일이 Java 9에 추가된 [List.of](https://docs.oracle.com/javase/9/docs/api/java/util/List.html)를 사용한다. `javac --release 8`은 cannot find symbol로 exit 1이다. 증거: java8-api-compile. 실제 전체 Boot 2 빌드는 미실행이다.

최소 권고: Java 8 지원 컬렉션 생성 방식으로 템플릿을 분기한다. 우회: 해당 예제를 그대로 적용하지 않고 API baseline을 확인한다.

### F22 — Boot 4 테스트 패키지·기술별 starter 분리를 반영하지 않음 [P1 / 정적 확인]

위치: [버전 참조:51](../references/version-compatibility.md#L51), [동일 문서:142](../references/version-compatibility.md#L142), [MVC 예제:17](../examples/java/OrderControllerTest.java#L17), [Gradle 예제:29](../examples/gradle/build.gradle.kts#L29), [생성 역할:189](../agents/test-code-generator.md#L189).

3.4+/4.x 공통 분기에서 이전 WebMvcTest import를 사용한다. Boot 4의 [WebMvcTest](https://docs.spring.io/spring-boot/4.0/api/java/org/springframework/boot/webmvc/test/autoconfigure/WebMvcTest.html)는 `org.springframework.boot.webmvc.test.autoconfigure`, [DataJpaTest](https://docs.spring.io/spring-boot/4.0/api/java/org/springframework/boot/data/jpa/test/autoconfigure/DataJpaTest.html)는 `org.springframework.boot.data.jpa.test.autoconfigure`다. `starter-test`만으로 기술별 slice 인프라를 보장할 수 없다. [공식 migration guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide).

최소 권고: Boot 4 분기에서 imports와 MVC/JPA/security 등 실제 테스트 starter를 함께 결정한다. 우회: 해당 Boot 버전 API/의존성으로 검토한다. 실제 Boot 4 생성 프로젝트 컴파일은 미실행이다.

### F23 — Boot 2 Maven 예제의 JDK 8 release 옵션 충돌 [P1 / 정적 확인]

위치: [Boot 2 Maven 예제:9](../examples/maven/pom-snippet-boot2.xml#L9), [동일 파일:16](../examples/maven/pom-snippet-boot2.xml#L16).

Boot 2.7.18 parent의 compiler 3.10.1과 `maven.compiler.release=8` 조합은 실제 JDK 8에서 --release를 지원하지 않는다. JDK 8의 source/target 전환 지원은 [compiler 3.13부터](https://maven.apache.org/plugins/maven-compiler-plugin/examples/set-compiler-release.html)다. Boot parent의 [고정 버전](https://raw.githubusercontent.com/spring-projects/spring-boot/v2.7.18/spring-boot-project/spring-boot-dependencies/build.gradle)을 대조했다.

최소 권고: 실행 JDK에 따라 source/target과 release 사용을 구별한다. 우회: JDK 8에서는 해당 compiler가 지원하는 source/target 설정을 사용한다. 실제 JDK 8 Maven 빌드는 미실행이다.

### F24 — JaCoCo 0.8.12와 Java 24–26 지원 선언 불일치 [P1 / 정적 확인]

위치: [지원 표](../README.md), `README.md:395–410`; [Gradle 예제:65](../examples/gradle/build.gradle.kts#L65), Maven 예제·버전 참조의 JaCoCo pin.

0.8.12는 Java 22 공식 지원·23 실험 지원이며 Java 24–26 classfile 지원은 없다. [공식 변경 이력](https://www.jacoco.org/jacoco/trunk/doc/changes.html). **실행 JVM이 24라는 것과 대상 classfile이 24라는 것은 구별한다.** 오래된 release로 컴파일한 코드까지 항상 실패한다고 주장하지 않는다.

최소 권고: 현재 pin에서 허용되는 classfile을 안내하고 미지원 조합을 조기에 거부한다. 업그레이드는 별도 결정 사항이다. 실제 Java 24–26 계측·리포트 실행은 미실행이다.

### F25 — 문서별 인덱싱 지시와 전체 교체 API 충돌 [P1 / 재현]

위치: [spec-reviewer:168](../agents/spec-reviewer.md#L168), [spec_doc_server.py:490](../mcp/spec_doc_server.py#L490), `index_docs` 및 snapshot publish.

역할은 복수 문서를 병렬 인덱싱하라고 하지만 각 호출은 전체 인덱스를 교체한다. a.md 다음 b.md를 인덱싱하면 a 추출은 criteria=0/partial이다. 증거: spec-first-index, spec-second-index, spec-first-extract-after-replacement. [SDK 2 동기 handler의 worker thread 실행](https://py.sdk.modelcontextprotocol.io/migration/#sync-handler-functions-now-run-on-a-worker-thread)도 병렬 호출의 마지막 publish 문제를 뒷받침한다. 실제 동시 완료 순서는 미실행이다.

최소 권고·우회: 모든 spec paths를 한 index_docs 호출에 넣는다. snapshot의 원자적 publish만으로 문서별 호출의 누락은 해결되지 않는다.

### F26 — 청크 overlap 재합성으로 규칙 중복·잘림 [P2 / 재현]

위치: [spec_doc_server.py:230](../mcp/spec_doc_server.py#L230), `_chunk_text`; [동일 파일:717](../mcp/spec_doc_server.py#L717), 추출용 재합성.

1,200자 청크/150자 overlap 경계의 must 문장 하나가 잘린 rule과 완전한 rule 두 개가 된다. 증거: spec-chunk-overlap. Gherkin 문맥의 실제 변형 범위는 추가 확인이 필요하다.

최소 권고: 원문을 추출 근거로 사용하거나 overlap 좌표를 보존해 복원한다. 우회: 추출 결과를 원문과 비교해 중복·잘린 criteria를 승인 전에 정리한다.

### F27 — 입력 형식 예시와 실제 지원·디렉터리 발견 계약 불일치 [P2 / 재현 및 정적 확인]

위치: [ingest-specs:38](../skills/ingest-specs/SKILL.md#L38), [spec-reviewer:37](../agents/spec-reviewer.md#L37), [spec_doc_server.py:225](../mcp/spec_doc_server.py#L225), `_SUPPORTED_EXTENSIONS`.

지원은 `.md/.txt/.adoc/.rst/.text`다. YAML/PDF 예시와 다르다. 명시 파일은 오류를 표시하지만 docs 디렉터리의 md+yaml은 YAML을 조용히 제외하고 status=ok다. 증거: spec-directory-unsupported-format.

최소 권고: 예시·발견 누락·fallback 정책을 일치시킨다. 우회: 원본을 보존하며 지원 텍스트로 변환하고 읽힌 파일 목록을 확인한다. PDF parser 추가를 이번 감사의 수정 범위로 간주하지 않는다.

### F28 — 잘못된 문서 인코딩을 오류 없이 손상시킴 [P2 / 재현]

위치: [spec_doc_server.py:210](../mcp/spec_doc_server.py#L210), `_safe_read`; build 서버의 `_read_text`도 UTF-8 replace 사용.

CP949 문서의 한글이 replacement 문자로 바뀌지만 read error는 없다. 증거: spec-cp949-read. 인덱스나 버전 판단이 원본 의미와 달라질 수 있다. UTF-16 전체 입력의 추출 영향은 미실행이다.

최소 권고: 지원 인코딩을 명시하고 디코딩 손실을 진단한다. 우회: UTF-8 변환 결과를 원문과 비교한다.

### F29 — Claude Bash 설정의 DATA 경로가 MCP와 다름 [P1 / 정적 확인·직전 경계 관찰]

위치: [setup-harness:74](../skills/setup-harness/SKILL.md#L74), [environment-setup:73](../references/environment-setup.md#L73), [launch.cjs:33](../mcp/launch.cjs#L33), [persist_astcli_jar.py:40](../scripts/persist_astcli_jar.py#L40), [setup_jdtls.py:75](../scripts/setup_jdtls.py#L75).

공식 [Claude 환경 변수 계약](https://code.claude.com/docs/en/plugins-reference#where-each-variable-resolves)에 따르면 Bash에는 plugin 변수가 export되지 않는다. ROOT의 Markdown 치환만으로 DATA가 전달되지는 않는다. 문서의 E6/E7 셸 명령은 설치 캐시의 `.plugin-data`를 쓰고 MCP/LSP는 실제 영속 DATA를 쓸 수 있다. 업데이트 후 jar/JDT를 잃거나 찾지 못한다. 관리형 Python pin도 다른 DATA에서 찾게 된다.

최소 권고: 확인한 영속 DATA를 셸 자식 환경으로 전달한다. 우회: Bash·MCP·LSP의 실제 DATA와 jarPersisted를 대조한다. 실제 Claude 설치·업데이트 세션은 미실행이다.

### F30 — JDT 검사와 실행의 Java 선택 우선순위 불일치 [P2 / 정적 확인·직전 경계 재현]

위치: [setup_jdtls.py:131](../scripts/setup_jdtls.py#L131), `detect_java_major`; [jdtls-launcher.cjs:97](../mcp/jdtls-launcher.cjs#L97).

JAVA_HOME=17·PATH=21에서 setup은 최고 major 21로 통과하지만 pinned JDT LS 1.60.0의 [launcher](https://raw.githubusercontent.com/eclipse-jdtls/eclipse.jdt.ls/v1.60.0/org.eclipse.jdt.ls.product/scripts/jdtls.py)는 JAVA_HOME 17을 먼저 선택하고 거부한다.

최소 권고: 검사한 실행 파일을 실제 실행에도 사용한다. 우회: JAVA_HOME·PATH의 LSP JVM을 일치시킨다. 실제 두 JDK를 둔 LSP initialize는 미실행이다.

### F31 — Windows JDT launcher가 관리형 Python 선택을 재사용하지 않음 [P2 / 정적 확인]

위치: [jdtls-launcher.cjs:33](../mcp/jdtls-launcher.cjs#L33), [동일 파일:63](../mcp/jdtls-launcher.cjs#L63), [setup_jdtls.py:233](../scripts/setup_jdtls.py#L233).

하네스는 py -3/관리형 uv Python으로 준비할 수 있지만 JDT 1.60.0 [Windows launcher](https://raw.githubusercontent.com/eclipse-jdtls/eclipse.jdt.ls/v1.60.0/org.eclipse.jdt.ls.product/scripts/jdtls.bat)는 bare `python`을 실행한다. bare python이 없거나 Store alias면 LSP가 실패할 수 있다.

최소 권고: 검증한 Python 경로를 JDT 실행에 전달한다. 우회: JDT launcher가 실제 호출하는 python을 확인한다. 클린 Windows 설치는 미실행이다.

### F32 — jar 교체 중 사본 소실·손상 사본의 최신 판정 [P2 / 재현]

위치: [persist_astcli_jar.py:88](../scripts/persist_astcli_jar.py#L88), `status`; [동일 파일:113](../scripts/persist_astcli_jar.py#L113), `persist`.

기존 jar 삭제 뒤 copy2에 IO 실패를 주면 기존 사본이 사라진다. ZIP이 아닌 부분 파일과 맞는 source marker만 있어도 upToDate=true다. 증거: persist-copy-failure, previous-jar-lost-on-copy-failure, corrupt-jar-considered-current. 동시 실제 독자와 중단 복사는 미실행이다. [Python replace/copy 의미](https://docs.python.org/3.14/library/os.html#os.replace).

최소 권고: 임시 사본 검증 후 원자적 교체하고 binary와 marker를 검증한다. 우회: 실제 java -jar 호출까지 확인하여 손상 사본을 재빌드·영속화한다.

### F33 — Windows 부모 종료 후 서버 자식 잔존 [P2 / 직전 실제 프로세스 재현]

위치: [launch.cjs:257](../mcp/launch.cjs#L257), signal forwarding; [bootstrap.py:285](../mcp/bootstrap.py#L285), Windows subprocess 대기.

bootstrap 부모를 종료한 뒤 자체 생성한 sleep 서버 자식이 생존했다. 즉시 정리했다. Node가 직접 자식까지만 signal을 전달하고 bootstrap은 하위 종료 처리가 없다. [Node 24.12 child kill](https://nodejs.org/download/release/v24.12.0/docs/api/child_process.html#subprocesskillsignal). 증거: prior-observations runtime.windows-parent-termination.

최소 권고: 취소·timeout의 process tree 종료를 확인한다. 우회: 중단 뒤 해당 실행의 잔존 PID·빌드 잠금을 확인한다. 실제 Codex/Claude가 별도 tree cleanup을 하는지는 미검증이다.

### F34 — 최초 uv 설치 로그의 MCP stdout 오염 [P1 / 정적 확인·직전 스트림 관찰]

위치: [launch.cjs:113](../mcp/launch.cjs#L113), Windows uv installer spawn의 inherited stdout.

Python·uv가 없는 첫 시작에 installer의 정보 출력이 MCP stdout으로 전달될 수 있다. 조사 시 [공식 uv 0.12.23 PowerShell installer](https://releases.astral.sh/installers/uv/latest/uv-installer.ps1)는 Write-Information/Continue를 사용했고 같은 PowerShell primitive가 stdout에 출력됐다. [MCP stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#stdio)는 비프로토콜 stdout을 금지한다.

최소 권고: provisioning 로그를 protocol stdout과 분리한다. 우회: 런타임을 연결 전에 준비한다. 실제 installer·클라이언트의 cold handshake 실패는 미실행이다.

### F35 — Windows 대소문자 변형이 산출물 가드를 누락 [P2 / 직전 함수 경계 재현]

위치: [guard-gate-artifacts.py:625](../scripts/guard-gate-artifacts.py#L625), basename 집합; [동일 파일:630](../scripts/guard-gate-artifacts.py#L630), 테스트·test_docs 문자열 검사.

mocked active run의 동일 payload가 lowercase에서는 deny, `Src/Test/Java`에서는 allow={}다. Windows 기본 [파일명 비교](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)는 이 경로들을 동등하게 취급한다. 실제 Claude Write/Edit는 미실행이다.

최소 권고: 물리 경계와 Windows 비교 규칙을 일치시킨다. 우회: 호스트 지침의 승인·선행 단계 확인을 유지한다. Codex는 해당 Claude 가드를 사용하지 않는다.

### F36 — 독립 상태줄 launcher의 UTF-8 누락 [P2 / 정적 확인·직전 인코딩 관찰]

위치: [상태줄 launcher:80](../scripts/test-autoevermation-statusline-launch.cjs#L80), [Python 상태줄:328](../scripts/test-autoevermation-statusline.py#L328).

전역 상태줄은 MCP launcher의 UTF-8 환경 설정을 사용하지 않는다. Windows Python 3.14/cp949에서 resume 문자 ↩를 encode하면 UnicodeEncodeError다. 실제 전역 상태줄에서의 증상은 미실행이며 fallback delegate만 표시될 가능성이 있다. [Python UTF-8 mode](https://docs.python.org/3.14/library/os.html#python-utf-8-mode).

최소 권고: 상태줄 자식의 인코딩 계약을 명시한다. 우회: 상태줄 출력보다 실제 산출물을 확인한다.

### F37 — 기존 Windows 상태줄의 셸 의미가 바뀜 [P2 / 정적 확인]

위치: [Python 상태줄:105](../scripts/test-autoevermation-statusline.py#L105), [CJS 상태줄:61](../scripts/test-autoevermation-statusline-launch.cjs#L61).

기존 delegate를 항상 cmd.exe로 실행한다. [Claude Windows statusline](https://code.claude.com/docs/en/statusline#windows-configuration)의 Git Bash/PowerShell 명령은 셸별 문법이므로 이전에 작동하던 조건식 등이 실패할 수 있다.

최소 권고: 원래 셸을 보존하거나 지원 셸을 명시한다. 실제 설치·delegate 실행은 미실행이다.

### F38 — 유효한 SDK 버전 문자열을 거부 [P3 / 재현: metadata mock]

위치: [bootstrap.py:61](../mcp/bootstrap.py#L61), `current_interpreter_has_mcp`.

`2.3.0+vendor.1`, `2.3`는 >=2.2,<3의 [PEP 440 범위](https://packaging.python.org/en/latest/specifications/version-specifiers/)에 맞지만 자체 regex는 거부한다. 실제 SDK API import가 가능한 환경에서 metadata만 바꿔 재현했다. 증거: sdkVersionBoundary. 실제 private SDK 배포 설치는 미실행이다.

최소 권고: 표준 버전 해석을 사용한다. 우회: 지원하는 정식 SDK 배포를 사용한다.

### F39 — Maven BOM이 plugin 버전을 관리한다는 설명 [P2 / 정적 확인]

위치: [Maven 예제:16](../examples/maven/pom-snippet.xml#L16), [동일 파일:30](../examples/maven/pom-snippet.xml#L30), [Boot 2 예제:22](../examples/maven/pom-snippet-boot2.xml#L22).

dependency BOM import와 parent pluginManagement를 혼동한다. Boot parent 예제에는 관리 버전이 있지만 기존 parent+BOM-only 대상에는 그대로 적용되지 않는다. [Boot 공식 parent 없이 사용하기](https://docs.spring.io/spring-boot/docs/2.7.18/reference/htmlsingle/#howto-use-spring-boot-without-a-parent-pom).

최소 권고: 대상의 effective plugin 버전을 근거로 판단한다. 우회: 상속된 compiler/Surefire/Failsafe 버전을 확인한다.

### F40 — Boot 2.2–2.3의 Vintage 설명 불일치 [P3 / 정적 확인]

위치: [RESEARCH_NOTES:113](../RESEARCH_NOTES.md#L113).

Vintage 제외라고 적었지만 [Boot 2.3.12 공식 testing 문서](https://docs.spring.io/spring-boot/docs/2.3.12.RELEASE/reference/html/spring-boot-features.html#boot-features-testing)는 starter-test의 Vintage 포함을 명시한다. 신규 Jupiter 생성과 기존 JUnit 4 테스트 공존 판단에 영향을 준다.

최소 권고: Boot별 기본 engine 구성과 프로젝트의 실제 exclusions를 구별한다. 기존 연구 기록은 이번 감사에서 수정하지 않았다.

### F41 — 구형 Gradle에서 Report.required DSL 사용 조건 [P2 / 정적 확인: 조건부]

위치: [Boot 2 Gradle 예제:59](../examples/gradle/build-boot2.gradle#L59), XML/HTML required 속성.

선언된 Gradle 5.x까지 예제를 일반화하면 required 속성이 없다. [공식 Report 소스](https://raw.githubusercontent.com/gradle/gradle/v6.9.4/subprojects/reporting/src/main/java/org/gradle/api/reporting/Report.java)는 이 속성의 도입을 6.1로 명시한다. **현재 Boot 2.7 예제를 충분히 새로운 Gradle에서 쓰는 경우에는 이 문제를 주장하지 않는다.**

최소 권고: 실제 wrapper 버전에 맞는 DSL을 선택한다. 구형 Gradle 실제 빌드는 미실행이다.

### F42 — 긴 Windows Codex DATA 경로의 SDK 설치 실패 [P2 / 기존 실행]

위치: [검증 기록:50](codex-validation.md#L50), launcher/bootstrap의 DATA/venv 경로.

기존 깊은 격리 Codex 홈에서 SDK 설치가 긴 경로 제한으로 실패했고, 짧은 별도 홈에서는 MCP 3종 연결이 성공했다. 이번 감사에서 재설치·레지스트리 변경은 하지 않았다.

최소 권고: 실패 경로와 DATA 위치를 진단 가능하게 안내한다. 우회: 검증된 짧은 데이터 경로를 사용한다. 모든 Windows 환경에서 실패한다고 일반화하지 않는다.

### F43 — 한글 Maven 경로에서 JaCoCo 데이터 경로 손상 [P1 / 기존 실행]

위치: [검증 기록:51](codex-validation.md#L51), Maven/JDK 17.0.7/JaCoCo 0.8.12 실행.

한글·공백 프로젝트 경로에서 테스트는 성공했지만 깨진 이름의 jacoco.ex에 기록되어 정상 XML이 없었다. 하네스는 JACOCO_REPORT_NOT_FOUND로 거부했다. 같은 경로의 Gradle은 통과했고 ASCII Maven 경로에서도 실제 빌드 검증이 성공했다.

최소 권고: JVM·agent 파일 경로 인코딩을 실제 조합에서 검증한다. 우회: 기록에서 확인된 ASCII 프로젝트 경로를 사용한다. 해당 환경에서는 가짜 완료를 보고하지 않은 점도 구분한다.

## 3. 추가 확인이 필요한 위험

다음은 확정된 결함 수와 분리한다. 과도한 전체 조합 실행 대신 조건별 최소 입력·기존 자료를 사용한다.

| ID | 위치·조건 | 위험 / 최소 확인·권고 |
|---|---|---|
| C01 | `_compute_staleness`, `_BUILD_FILES`, source scan | resources·스펙 내용·하위 모듈 빌드·소스 삭제·동일/복원 mtime·2초 내 변경은 현재 비교로 포착되지 않을 수 있다. 변경 종류별 재개 추천을 확인하고 실행 대상과 content fingerprint를 검토한다. |
| C02 | `_detect_boot_version`, `_scan_imports` | version catalog·convention plugin·상속/profile BOM·400파일/본문 읽기 제한이 프로파일 증거를 누락할 수 있다. 실제 effective 설정과 degraded/질문 여부를 비교한다. |
| C03 | `_run_subprocess`, E10, JDT/AST/빌드의 JVM | 분석용 Java 17/21과 구형 Gradle 실행 JVM의 동시 선택이 필요하다. [Gradle 공식 표](https://docs.gradle.org/current/userguide/compatibility.html)상 Java 17은 Gradle 7.3+, Java 21은 8.5+다. Gradle 5.x에 같은 JVM을 그대로 적용하는 조합을 지원 조합으로 간주하지 않는다. |
| C04 | launch Python install lock, bootstrap venv/pip lock | 설치 경쟁·죽은 설치·600초 stale 기준·300초 waiter·pip 전체 timeout 부재·POSIX flock 대기를 확인한다. 기존 정상 lock 구현 자체를 결함으로 단정하지 않는다. |
| C05 | spec-doc worker/index snapshot | 여러 root 동시 인덱싱·취소 후 늦은 publish·다중 세션 사용에서 요청별 snapshot과 root mismatch를 확인한다. 단일 프로젝트 snapshot은 현재 문서화된 제한이다. |
| C06 | spec `_safe_read`, `_chunk_text`, directory recursion | UTF-16/BOM, 큰 문서, 접근 거부, symlink/junction 경계, 파일 수 증가의 메모리·응답시간·추출 손실을 확인한다. PDF·암호화 PDF는 현재 미지원 입력으로 구분한다. |
| C07 | `mcp/pyproject.toml` console entrypoint | wheel에는 서버 모듈만 있고 plugin manifest·Java CLI source/jar·bootstrap이 없다. standalone pip 설치가 플러그인 전체 설치를 대체하는지 보장하지 않는다. 그 경로를 사용할 경우 외부 jar·DATA 계약을 확인한다. |
| C08 | Maven 예제 report phase=test, CI mvn verify | Failsafe가 뒤에 실행되면 먼저 생성한 XML이 IT coverage를 놓칠 수 있다. MCP의 withCoverage 경로는 verify 뒤 jacoco:report를 추가하므로 그 경로까지 같은 결함으로 단정하지 않는다. 기존 CI 경로의 실제 report 시점·exec 합산을 확인한다. |
| C09 | MVC 예제 `spring.security.enabled=false`, Boot 4 기술별 환경 | 기본 [WebMvcTest의 security 자동 구성](https://docs.spring.io/spring-boot/3.4/api/java/org/springframework/boot/test/autoconfigure/web/servlet/WebMvcTest.html)과 앱의 실제 보안 설정을 확인한다. 이 property를 범용 보안 해제 수단으로 가정하지 않는다. Boot 4 security test starter/Jackson 3 mapper와 fixture의 호환성도 실제 기술별 테스트에서 확인한다. |
| C10 | 호스트·경로·플랫폼 행렬 | 실제 앱 UI 설치, Claude 버전별 hook payload·LSP initialize, ARM/x86, macOS/Linux, Windows UNC/Store alias/긴 경로/권한 없는 DATA, offline/proxy 실패를 확인한다. cmd metacharacter 거부·Codex hooks={}·JDT/상태줄 제외는 문서화된 제약으로 구분한다. |

## 4. 지원 범위와 실제 검증 범위

### 버전 경계

| 대상 | 현재 근거 | 남은 실행 범위 |
|---|---|---|
| Boot 2.0–2.1 / Java 8 / JUnit 4 | 템플릿·공식 문서 대조, List.of release 8 실패 | 실제 생성 프로젝트·JUnit 4 테스트·커버리지 |
| Boot 2.2–2.7 / Java 8+ / Jupiter | compiler/engine/DSL 계약 확인 | JDK 8 Maven, 2.2·2.7 대표 경계 |
| Boot 3.0–3.3 / Java 17 / MockBean | 기존 Boot 3.2 실제 Gradle/Maven fixture | 다른 minor/대상 프로젝트·기술별 slice |
| Boot 3.4–3.5 / MockitoBean | 프로파일·공식 API·스킬 대조 | 실제 생성·컴파일·컨텍스트 초기화 |
| Boot 4.x / Java 17+ | migration/API/모듈 계약 확인 | MVC/JPA/security/Jackson 3 실제 프로젝트 |
| Java 17 / JavaParser 3.28.2 | 이번 실제 CLI, 한글·record·중첩·오버로드·파싱 실패 | full classpath/generated roots |
| Java 21·24–26 | 공식 Gradle/JaCoCo/JDT/Byte Buddy 계약 | 실제 host/계측 조합 |
| Python 3.14 / SDK 2.3.0 | 이번 API import·SDK in-process 3서버 health/20도구 | 실제 host stdio·취소·cold install |
| Python 3.10–3.13 / SDK 허용 범위 | 선언·공식 SDK 계약 및 기존 자료 | 각 실제 interpreter·OS 조합 |

Java 8 대상과 하네스 JVM은 별도다. 컴파일 release/target, Gradle 실행 JVM, AST JVM, Claude LSP JVM을 혼동하지 않는다. [Gradle 표](https://docs.gradle.org/current/userguide/compatibility.html)는 Java 24/25/26의 실행 지원을 각각 8.14/9.1.0/9.4.0부터로 명시한다. Mockito/Byte Buddy는 실제 resolved 버전을 확인한다. [Byte Buddy 공식 표](https://raw.githubusercontent.com/raphw/byte-buddy/master/README.md)는 Java 24에 1.15.4, 25+에 1.17.0을 제시하며 이는 JaCoCo의 classfile 지원을 대신하지 않는다.

### 호스트·플랫폼

| 조합 | 확인 내용 | 확인하지 않은 내용 |
|---|---|---|
| Windows Codex CLI/app-server | 기존 Git 설치·portable 매니페스트 로딩·MCP 3종 연결 | 데스크톱 Plugins UI 클릭·대화형 전체 승인/생성/보정 |
| Windows Claude | 코드/공식 환경·hook·LSP 계약, 직전 기존 hook 9개·상태줄 3개 검사 | 실제 DATA 전달·업데이트·두 JDK LSP·delegate shell |
| Windows 공용 MCP/Java | 이번 SDK in-process, JVM·경계 입력 | 실제 cold installer·host cancellation tree |
| macOS/Linux/ARM | 코드 경로와 공식 계약 정적 확인 | 실제 설치·stdio·빌드·LSP·권한/프로세스 종료 |

공식 패키징과 호스트 계약도 대조했다. [OpenAI portable plugin](https://developers.openai.com/plugins/build/plugins)의 ROOT/DATA·MCP 구성, Codex hooks={}·순차 역할 재사용·질문 부재 시 응답 대기, Claude의 현재 hook args·namespaced agent_type·중첩 decision/context 형식은 이번 조사에서 결함으로 분류하지 않았다. Codex의 LSP=false는 의도된 정상 경로다. Claude의 Write/Edit 가드가 모든 shell 쓰기를 통제한다고 해석하지 않는다.

## 5. 실행 기록·재현 방법·완료 판정

### 이번 감사의 실행

- `boundary_probes.py`: 26개 관찰. 버전·capability·리포트·재개·스펙·root 거부·jar 실패 입력을 기록했다. 이것은 새 테스트 스위트의 pass 수가 아니다.
- `ast_observations.py`: 실제 JVM에서 8개 소스 입력, release 8 List.of 컴파일, mocked Java 8 capability 경계를 기록했다.
- `sdk_observations.py`: 실제 SDK 2.3.0 in-process에서 health 3종과 도구 5+4+11개를 확인했다. a.Service 조회에 두 FQCN이 섞이는 것도 확인했다. metadata mock의 PEP 440 판정 3개를 비교했다.
- 직전 읽기 전용 조사의 hook/statusline·프로세스·인코딩·protocol 관찰은 출처를 유지하여 재사용했다. 원본 프로세스 로그가 저장되지 않은 관찰은 요약 증거임을 표시했다.

위 일회성 스크립트·입력·JSON·로그는 저장소 루트의 무시된 `_workspace/compatibility-audit/`에 있으며 배포 파일이 아니다. 실행은 repository root에서 기존 SDK 환경과 UTF-8을 사용했다.

```powershell
$env:PYTHONUTF8 = '1'
& .\.mcp-venv\Scripts\python.exe _workspace\compatibility-audit\boundary_probes.py
& .\.mcp-venv\Scripts\python.exe _workspace\compatibility-audit\ast_observations.py
& .\.mcp-venv\Scripts\python.exe _workspace\compatibility-audit\sdk_observations.py
```

이 스크립트는 해당 로컬 작업공간의 증거 재생 방법이다. clean clone에 포함된 실행 명령으로 오인하지 않는다. 임시 입력은 실제 코드·보고서 수집 경로를 확인하기 위한 최소 자료이며, 플러그인 tests/에는 파일을 추가하지 않았다. 네트워크 priming·패키지 설치·전역 설정 변경은 하지 않았다.

### 기존 검사·통합 자료

기존 `_workspace/unittest-final.log`는 197개 중 **190 통과·1 실패·3 오류·3 skip**이다. 4개 실패/오류는 변경 전 `67bb22f`에서도 재현된 기존 문제로 기록되어 있다. 이번 감사에서 전체 suite를 반복 실행하거나 기존 실패를 수정하지 않았다.

| 기존 실패/누락 | 위치·원인 | 감사에서의 의미 |
|---|---|---|
| task output 검사 NameError | [test_build_contract_v2:150](../tests/test_build_contract_v2.py#L150), undefined server | F10을 통과/안전으로 판단하는 근거가 될 수 없다. |
| task report 경로 assertion | [동일 파일:92](../tests/test_build_contract_v2.py#L92), POSIX `/` 문자열 가정 | Windows 경로 비교의 기존 검사 문제다. 실제 리포트 혼입 결함으로 단정하지 않는다. |
| symlink 2개 권한 오류 | [test_pipeline_v2:537](../tests/test_pipeline_v2.py#L537), [동일 파일:565](../tests/test_pipeline_v2.py#L565), WinError 1314 | 권한 있는 환경의 실제 alias guard 검증은 남아 있다. |
| Windows stdio 3개 skip | [test_mcp_stdio_v2:24](../tests/test_mcp_stdio_v2.py#L24), POSIX fixture | 기존 별도 Windows live 자료와 이번 in-process 검증을 구분한다. |

기존 `_workspace/real-builds-final/results.json`과 [검증 기록](codex-validation.md)은 ASCII 경로의 Gradle/Maven 실빌드, 한글 메서드 선택, custom integration task, 실패·보정, skip/없는 테스트 거부, coverage 포함/제외 입력을 담고 있다. 이 결과를 Boot 2/4·모든 OS·대화형 전체 E2E 성공으로 확대하지 않는다.

### 후속 수정 순서

1. F01–07의 프로파일·capability·모듈·최신성·승인 증거 판정을 먼저 바로잡는다. 잘못된 정상/재개 추천을 줄이는 범위다.
2. F11·F13·F15–16의 AST 입력/출력 계약을 복구하고 F21–24의 버전별 생성·계측 조건을 일치시킨다.
3. F25·F29·F34의 인덱싱/영속 DATA/초기 stdio 경로를 정리한다.
4. 나머지 P2는 실제 발생 환경에 따라 최소 수정한다. P3와 추가 확인 항목은 지원 설명·증거를 보완한다.

후속 수정에서도 생성 테스트의 JUnit 실행·보정·JaCoCo·적합성·승인을 유지한다. 별도 메타 테스트, mutation testing, 의무 RED–GREEN TDD, 중복 리뷰·승인 단계를 추가하지 않는다. 현재 버전의 schemaVersion:2·기존 도구 이름·Claude root 생략 동작과 기본 오프라인 정책을 유지한다.

### 감사 완료 기준

구조 영역별 읽기·계약 대조, 각 F 항목의 위치·조건·영향·증거 수준·최소 권고, C 항목의 미확정 이유, 버전/호스트별 미실행 범위를 기록했다. 최종 파일·링크·증거 점검은 로컬 `final-check.json`에 기록한다. 전체 호환성이 통과했다거나 위 결함을 수정했다고 주장하지 않는다.
