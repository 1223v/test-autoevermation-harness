# 라이브 검증 결과 (2026-06-25)

실제 `mcp[cli]` SDK 설치 + 실제 Spring 샘플로 end-to-end 검증한 증거.

## 1. MCP stdio 핸드셰이크 (3개 서버)

`mcp[cli]`를 venv에 설치 후, MCP 공식 클라이언트(`ClientSession` + `stdio_client`)로 각 서버에 연결해 `initialize` → `tools/list` → `resources/list` → `prompts/list`를 수행. (도구: `verify_stdio.py`)

| 서버 | initialize | tools | resources | prompts |
|---|---|---|---|---|
| repo-ast | ✅ serverInfo.name=repo-ast | 4 (extract_test_targets, list_spring_components, parse_java_file, resolve_symbol) | 2 (ast://index, ast://dependency-graph) | 1 (explain_target_shape) |
| spec-doc | ✅ serverInfo.name=spec-doc | 3 (extract_acceptance_criteria, index_docs, search_requirements) | 2 (spec://glossary, spec://requirement-matrix) | 1 (review_specs_for_testing) |
| build-test | ✅ serverInfo.name=build-test | 7 (coverage_gate, detect_build_tool, list_test_tasks, parse_jacoco_report, parse_junit_xml, parse_pitest_report, run_targeted_tests) | 2 (build://metadata, build://test-reports) | 1 (suggest_test_command) |

→ 세 서버 모두 정상 MCP 서버로 동작(핸드셰이크 + capability 협상 성공).

## 2. 실제 Spring 샘플 dry-run

샘플: `sample-spring-app/` (Spring Boot 4.1.0, `OrderController` → `OrderQueryService`(분기 할인 로직) → `Order`/`OrderDetailDto`). MCP 클라이언트로 실제 도구 호출. (도구: `dryrun_sample.py`)

**repo-ast.extract_test_targets** (JavaParser jar 경유) — status `ok`, 6개 클래스 정확 분류:
- `OrderController` → **controller**
- `OrderQueryService` → **service** (`getOrder`, `applyDiscount`)
- `Order`/`OrderDetailDto`/`OrdersApplication`/`OrderNotFoundException` → pojo
- 의존 그래프: `OrderController → OrderQueryService`(field), `OrderQueryService → Map<String,Order>`(field) ✓ 협력객체 정확 추출

**build-test.detect_build_tool** → `{"buildTool":"gradle","wrapper":false}` ✓
**build-test.list_test_tasks** → `test`, `jacocoTestReport`, … ✓

→ MCP 클라이언트 → 서버 → JavaParser → 실제 Spring 코드까지 전 구간 동작 확인.

## 3. Spring Boot 2.x end-to-end 드라이런 + 실제 빌드 (2026-06-26, v0.3.0)

샘플: `sample-spring-boot2/` (**Spring Boot 2.7.18**, javax 네임스페이스, Java 8 베이스라인). 도구: `verification/dryrun_boot2.py` + 실제 `mvn test`.

**3-1. 버전 인식 MCP 파이프라인** (MCP 클라이언트 → build-test/repo-ast 서버) — `dryrun_boot2.py` 결과 **ALL PASS**:

| 단계 | 결과 |
|---|---|
| `detect_build_tool` | `gradle` ✓ |
| `detect_spring_profile` | bootMajor=**2**, namespace=**javax**, junitEngine=**jupiter**, mockAnnotation=**@MockBean**, mockImport=`org.springframework.boot.test.mock.mockito.MockBean`, javaBaseline=**8** ✓ (7/7 assertion PASS, `versionSource=build.gradle`) |
| `extract_test_targets` | `OrderController`→**controller**, `OrderQueryService`→**service** ✓ |
| 생성기 관용구 선택 | `@WebMvcTest + MockMvc + @MockBean`, `javax.persistence.*`, Jupiter `@Test/@DisplayName` ✓ |

**3-2. 프로파일 생성물의 실제 컴파일·실행** (Maven, Boot 2.7.18 런타임):

하네스가 선택한 Boot 2.x 프로파일대로 생성한 테스트 2종을 `mvn test`로 실제 컴파일·실행:
- `OrderControllerTest` — `@WebMvcTest` + `@MockBean OrderQueryService` (실제 Boot 2.7 컨텍스트 로드, `MockitoContextCustomizer` 동작 확인): **2/2 pass**
- `OrderQueryServiceTest` — `@ExtendWith(MockitoExtension.class)` + `@ParameterizedTest @CsvSource`(할인 분기 경계값): **7/7 pass**
- 결과: `Tests run: 9, Failures: 0, Errors: 0` → **BUILD SUCCESS**

> 1차 실행은 `javax.validation` 미해결로 컴파일 실패 → Boot 2.3+가 validation을 분리한다는 사실대로 `spring-boot-starter-validation`을 추가(빌드 보정)해 통과. (하네스 repair 루프가 다루는 `TEST_COMPILE_FAILED` 유형과 동일)

**3-3. 하네스 파서로 결과 수렴**: `build-test.parse_junit_xml`(surefire) → `status=ok, passed=9, failed=0` ✓ — MCP 파이프라인이 실제 빌드 산출물까지 정확히 파싱.

→ **Boot 2.x는 분석 dry-run을 넘어 실제 컴파일·실행까지 전 구간 검증 완료.** 버전 프로파일 감지 → javax/@MockBean/Jupiter 생성 → 실 Boot 2.7 런타임 통과.

## 참고: 완전 빌드/실행 범위

`./gradlew test`(테스트 실제 실행 + JaCoCo/PITest 리포트 생성)는 Gradle wrapper와 네트워크 의존성 다운로드가 필요해 본 검증 환경에서는 분석 단계까지만 dry-run했다. 커버리지/뮤테이션 **파서**는 합성 리포트로 별도 검증 완료(README/CHANGELOG 참조). 실제 프로젝트에서는 `pip install -r mcp/requirements.txt` + (선택) JavaParser jar 빌드 후 `/spring-test-harness:full-pipeline`로 전체 실행한다.
