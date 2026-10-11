# 호환성 실행 계약 (0.35.1)

이 문서는 기존 승인·반복 종료 절차에 적용하는 공용 계약이다. 별도 승인 단계나 플러그인 테스트를 추가하지 않는다.

## 빌드·보고서·재개

- Maven은 XML의 Boot parent/BOM과 properties를 읽는다. 미확정 값은 오프라인 effective POM으로 확인하고 실패하면 질문/보류한다. pluginManagement의 존재만으로 활성 JaCoCo를 인정하지 않는다. `prepare-agent`와 `report` 바인딩, skip, XML을 확인한다.
- Gradle의 주석은 설정이 아니다. 실제 오프라인 configuration에서 Test/JaCoCo 태스크·프로젝트 디렉터리·보고서 경로를 확인한다. `configurationVerified:false`이면 정적 신호만 얻은 것이므로 버전 카탈로그·convention plugin·조건식은 소스를 읽고 확인한다. 임의 최신 Boot 프로파일을 가정하지 않는다.
- `run_targeted_tests`, `list_test_tasks`, `detect_spring_profile`, `detect_build_capabilities`에는 선택적 `java_home`을 전달할 수 있다. 빌드 JVM, AST JVM(17+), Claude JDT JVM(21+)은 각각 확인하며 전역 JAVA_HOME을 변경하지 않는다. 대상 Java 8–26은 Boot/Gradle/JUnit의 실제 지원 조합에서만 사용한다.
- `run_targeted_tests`와 `parse_junit_xml`의 `report_dirs`는 확정한 프로젝트 내부 디렉터리 목록이다. `parse_jacoco_report`/`coverage_gate`/`detect_pipeline_state`의 `report_paths`로 필요한 XML만 선택하고, 실제 aggregate임을 확인했을 때만 `aggregate_report`를 지정한다. 상대 경로는 root 기준이며 루트 이탈을 거부한다. 커스텀 경로는 config의 기존 `reportDir` 등에서 이 인자로 전달한다.
- 모듈별 소스와 보고서를 확인한다. 일반 루트 XML로 하위 모듈을 대신하지 않는다. 누락 모듈, aggregate 범위 불명, 겹치는 클래스 보고서는 partial이며 게이트를 통과하지 않는다. BRANCH만 없고 실제 측정 클래스·다른 카운터가 있으면 분기 없는 코드로 N/A 처리한다. 모든 카운터가 없거나 측정 대상이 없으면 실패한다.
- `_workspace/build-test-evidence.json`은 실행 입력과 보고서의 SHA-256이다. 소스·리소스·빌드·스펙·설정의 변경/삭제를 감지하며 실행 중 입력이 바뀌면 성공을 기록하지 않는다. 낡거나 누락된 지문으로 테스트/커버리지를 건너뛰지 않는다. 이 파일을 수동으로 성공 증거처럼 작성하지 않는다.
- 폴더나 INDEX만으로 생성 출처를 인정하지 않는다. 승인된 SC의 ID와 실제 테스트 `scenarioRef`를 연결한다. pending 승인, 연결 누락이면 생성/승인 단계로 돌아간다. 완료는 승인·현재 JUnit·현재 JaCoCo·최신 시나리오 적합성까지 확인한 뒤 기록한다.
- 커버리지 재실행 전 기존 실행 데이터(.exec)의 누적/append 설정과 task 범위를 확인한다. MCP는 확정한 해당 태스크의 이전 XML을 제거하며, 알려진 해당 실행 데이터만 정리한다. 경로를 모르면 확인하고 보류한다. 다른 태스크나 모듈 데이터를 지우거나 오래된 데이터 합산을 최신 실행으로 간주하지 않는다.

## AST와 스펙

- JavaParser 3.28.2 CLI는 UTF-8을 사용한다. `analysis_context`에 `javaVersion`(8–26), 프로젝트 내부 `sourceRoots`, 확인된 dependency `classpath` jar 목록을 전달한다. 생략 시 CURRENT(26) 문법이므로 프로젝트의 실제 source level을 확인해 전달한다. 실제 Java 8 API 유효성은 빌드 컴파일로 확인한다.
- 프로젝트 외 dependency jar는 기존 REPO_AST_ALLOW_ROOT 경계를 넓히지 않는다. 경계 미설정 시에만 기본 Maven/Gradle 캐시의 jar를 프로젝트 내부 `classpathEvidence` 파일(빌드가 확인한 절대 jar 경로, 한 줄에 하나)과 대조해 허용한다. 커스텀 캐시/미확인 classpath는 추측하지 않고 보류한다.
- 레코드·열거형·중첩 타입, file/fields/methods, publicMethods를 구분한다. 오버로드별 `methodCallsBySignature`/`methodCallDetailsBySignature`를 우선 사용한다. legacy 이름별 map은 합집합이다. resolved declaringType/메서드 서명 또는 필드 타입으로 receiver를 확인하고, 동명 메서드의 scope가 불명확하면 적합성 통과를 추측하지 않는다.
- 파싱 문제와 미해결 return/parameter/field/extends/annotation 심볼을 기록한다. JavaParser 미설치/Java 17 미만은 실패다. 구조가 일부 나왔다고 의미가 확정된 것은 아니다. 생성에 필요한 미해결 의미는 소스·컴파일·질문으로 확인하거나 대상을 보류한다.
- `index_docs`는 **모든 스펙 경로를 한 번에** 전달한다. 문서별 병렬 호출은 금지한다. 한 MCP 프로세스는 한 루트의 인덱스만 보관하며 다른 프로젝트는 재인덱싱한다. 최신 요청만 완성된 스냅샷을 게시하고 취소/뒤늦은 요청이 덮어쓰지 않는다.
- 지원: `.md/.txt/.adoc/.rst/.text`, UTF-8(BOM 허용). PDF/YAML/DOCX/UTF-16/CP949는 지원으로 광고하지 않는다. 변환은 사용자 승인 범위에서 수행하고 출처를 기록한다. 미지원/읽기 실패/10 MiB 문서 및 5000개·50 MiB 인덱스 한도를 부분 결과로 알린다. 수용 기준은 마스킹한 원문에서 한 번 추출하고 검색 청크를 이어 붙이지 않는다.

## 런타임·템플릿

- Claude 수동 Bash 명령은 `node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" --data "${CLAUDE_PLUGIN_DATA}" script ...` 형식으로 DATA를 명시한다. Markdown 변수 치환과 셸 환경 export는 다르다. Codex는 확정한 PLUGIN_DATA를 같은 `--data` 인자로 전달한다. 설치 경로는 분석 대상 root가 아니다.
- cold installer 로그는 stderr에만 기록한다. 설치 잠금은 제한 시간과 살아 있는 owner를 확인한다. 종료/취소는 호출자가 소유한 프로세스 트리만 정리한다. DATA가 읽기 전용·과도하게 길어 실패하면 실제 경로와 오류를 보고하며 자동 이동/레지스트리 변경을 하지 않는다. Windows 문제가 재현되면 공식 호스트 설정으로 짧은 DATA/CODEX_HOME 경로를 선택한다.
- AST jar는 CRC 검사·SHA-256·소스 지문을 거쳐 영속화한다. 쓰기는 프로세스 잠금으로 직렬화하며 `astcli-state.json`의 원자 교체가 commit point다. 기존 분석 시작과 충돌하지 않도록 이전 immutable jar를 보관하고 manifest로 현재 사본을 선택한다. health에서 jarIntegrityVerified/jarStale을 확인한다. 예전 지문만 있는 설치는 E6에서 한 번 재빌드·영속화한다.
- Claude JDT는 실제 선택한 JAVA_HOME/HARNESS_JDT_JAVA_BIN을 검사하고 검증된 Python으로 `jdtls.py --java-executable`을 실행한다. PATH에 높은 Java가 있어도 낮은 JAVA_HOME을 성공으로 판단하지 않는다. 상태줄 delegate의 원래 설정과 Git Bash/PowerShell 셸을 보존한다. Codex에서는 모두 제외한다.
- JaCoCo 기본 예제는 **0.8.15**(Java 26 공식 지원), runtime 최소 Java 8이다. 기존 프로젝트 버전을 묵시적으로 올리지 않는다. [릴리스 근거](https://www.jacoco.org/jacoco/trunk/doc/changes.html).
- Java 8 예제는 Collections를 사용하고 JDK 8/compiler 3.10.1은 source/target=8로 설정한다. `--release`와 Java 9 API를 그대로 넣지 않는다. Maven dependency BOM은 pluginManagement를 대신하지 않는다. Boot 2.2/2.3 starter-test에는 Vintage가 기본 포함되고 2.4+에는 별도 필요하다. Gradle <6.1에는 reports xml.enabled/isEnabled를 사용한다.
- Boot 4 WebMvcTest: `org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest` + `spring-boot-starter-webmvc-test`; DataJpaTest: `org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest` + `spring-boot-starter-data-jpa-test`. Boot 3.4/3.5는 기존 슬라이스 import와 MockitoBean을 사용한다. Security 테스트는 필요할 때 Boot 4 security-test starter와 실제 인증 정책을 설정한다. `spring.security.enabled=false`를 일반 MVC 보안 해제 방법으로 사용하지 않는다. [Boot 4 공식 이행 가이드](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide).
- Maven CI는 verify를 실행하고 앞선 integration-test 데이터가 report/check에 포함되는지 확인한다. report 바인딩은 verify로 이동했으며 별도 IT exec 파일은 실제 합산 설정을 확인한다. 하네스의 verify 명령은 lifecycle 뒤 `jacoco:report`를 호출한다.

## Windows Maven의 한글 경로

`file.encoding=UTF-8`만으로 JaCoCo agent destfile 경로 인코딩 오류가 해결되지 않았다. [JaCoCo 이슈](https://github.com/jacoco/jacoco/issues/1735)와 실제 JUnit/exec/XML로 확인했다.

`detect_build_capabilities.windowsMavenAgent`는 위험과 조건부 제안만 반환한다. 기존 setup 승인 안에서 effective POM·실제 저장소 agent jar·기존 JVM/agent 옵션·module workingDirectory를 확인한다. 확정한 argLine의 JaCoCo 부분만 ASCII 상대 `destfile=target/jacoco.exec` 등으로 바꾸고 나머지 JVM 옵션은 보존한다. report의 dataFile은 동일 파일이어야 한다. 여러 모듈/별도 workingDirectory/미해결 argLine이면 질문·보류한다. 환경 옵션 전체 덮어쓰기나 무조건 CLI argLine 주입을 하지 않는다. 수정 후 최신 exec와 XML을 실제로 확인한다.

standalone Python wheel은 MCP 모듈만 제공한다. plugin/스킬/AST CLI 소스가 포함된 배포를 대체하지 않으며 별도 JavaParser jar가 필요하다. 실제 Codex GUI·모델 실행·다른 OS에서 실행하지 못한 항목은 통과로 기록하지 않는다.
