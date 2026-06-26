# Changelog

이 파일은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식을 따른다.
버전 관리는 [Semantic Versioning](https://semver.org/lang/ko/) 규칙을 따른다.

---

## [Unreleased]

---

## [0.3.0] - 2026-06-26

### Added

- **Spring Boot 2.0 – 4.x 버전 인식(하위호환)**: 대상 프로젝트의 Boot 버전 프로파일을 감지해 테스트
  관용구를 4개 축으로 자동 분기. 사용자 요구(최소 사양 2.x·구버전 포함, JUnit4 생성 포함, 미감지 시 인터뷰).
  - **`detect_spring_profile` MCP 도구**(`mcp/build_test_server.py`): build.gradle[.kts]/pom.xml/
    gradle.properties에서 Boot 버전, src/main의 `javax`↔`jakarta` import, src/test의 JUnit 엔진을 읽어
    `springProfile{bootVersion,bootMajor,namespace,junitEngine,mockAnnotation,mockImport,javaBaseline,
    gradleTestMode,degraded}` 반환. 혼용 프로젝트는 실제 소스 import를 우선(override + notes).
  - **버전 매트릭스 SSOT**: `RESEARCH_NOTES.md` §8 + `references/version-compatibility.md`(프로파일별
    전체 코드 템플릿). 출처: Boot 2.x System Requirements, Boot 3.0 Migration Guide, @MockitoBean(6.2)/
    @MockBean(deprecated 3.4) 공식 문서(웹 검증 2026-06-26).
  - **프로파일 구동 생성**: `generate-tests`·`test-code-generator`가 `@MockBean`(≤3.3)↔`@MockitoBean`(3.4+),
    `javax`↔`jakarta`, JUnit4(`@RunWith(SpringRunner.class)`/`org.junit.Test`/`@DisplayName` 없음)↔Jupiter를
    분기. `test-code-generator` tools에 `detect_spring_profile` 추가.
  - **인터뷰 폴백**: `configure-harness` 0.5단계에서 프로파일을 감지하고, 미감지+대화형이면 Boot 메이저/
    JUnit 엔진을 AskUserQuestion으로 질문, CI면 latest(4.x) 가정+경고. `HarnessConfig.springProfile` 추가.
  - **Boot 2.x 예제**: `examples/gradle/build-boot2.gradle`, `examples/maven/pom-snippet-boot2.xml`,
    `examples/java/OrderControllerTest_boot2_jupiter.java`(@MockBean+Jupiter),
    `OrderControllerTest_boot2_junit4.java`(@RunWith(SpringRunner.class)+JUnit4).

### Changed

- `plugin.json`·`marketplace.json` 0.2.2 → 0.3.0, 설명에 "Spring Boot 2.0–4.x 버전 인식" 반영.
- `full-pipeline`·`source-code-analyzer`·`scenario-generator`·`coverage-closer`·`mutation-analyst`·
  `generate-scenarios`의 하드코딩 `@MockitoBean` 관용구를 `springProfile` 기반으로 일반화.
- README 버전 호환표를 Boot 2.0–4.x 범위 + 프로파일 분기로 갱신.
- **JaCoCo 0.8.12는 Java 8 런타임 정상**, PITest는 Gradle 5.x/구버전에서 폴백 또는 graceful skip(문서화).

---

## [0.2.2] - 2026-06-25

### Changed

- **OMC 비의존 확정**: 빌드 단계에서만 oh-my-claudecode를 사용했고, 배포 산출물은 외부 플러그인에
  의존하지 않음을 검증·명문화. `subagent_type`을 잘못된 `spring-test-harness-plugin:` namespace에서
  **bare agent name**으로 정규화(9개 호출, 각 `agents/*.md`의 `name:`과 1:1 매칭)하여 네임스페이스
  가정 없이 해소되도록 함.
- 플러그인 디렉터리의 `.omc/` 운영 산출물 제거(`.gitignore`로 영구 차단).
- README 인트로의 "(Opus)" 표기 제거(모델 비의존과 일관).

### Added

- `DEPENDENCIES.md`: 네이티브 의존 항목 / 명시적 비의존 항목 / OMC 편의기능의 자체 구현 매핑
  (병렬=네이티브 `Task`, 상태=`_workspace/`+`record-timing.py`, 인터뷰=`AskUserQuestion`).

---

## [0.2.1] - 2026-06-25

### Changed

- **모델 이식성**: 전 에이전트(9종) frontmatter와 모든 스킬의 `Task(...)` 호출의 `model` 선언을
  강제 `opus`/`sonnet`에서 **`inherit`(현재 세션 모델)** 로 통일. opus를 사용할 수 없는 환경에서도
  하네스가 사용자의 현재 모델로 그대로 동작한다. 특정 티어 강제가 필요하면 해당 에이전트/호출에
  `model`을 명시 pin하면 된다.
- 문서 동기화: `REPORT.md` 버전표·에이전트 주석, `PRINCIPLES_AUDIT.md` #16, `README.md` 모델 항목,
  `full-pipeline/references/orchestration-detail.md`·`scripts/record-timing.py`의 예시값을 `inherit` 기준으로 갱신.

---

## [0.2.0] - 2026-06-25

> 검증 기준(웹 최신 공식문서): `RESEARCH_NOTES.md` 참조. Spring Boot 4.1.0, JaCoCo 0.8.12,
> gradle-pitest 1.19.0 / pitest-junit5-plugin 1.0.0, JavaParser symbol-solver 3.28.2,
> MCP Python SDK(FastMCP).

### Added

- **MCP 서버 3종 실제 구현(Python FastMCP)**: `mcp/repo_ast_server.py`, `mcp/spec_doc_server.py`,
  `mcp/build_test_server.py`. 공식 MCP Python SDK 기반 stdio 서버. `.mcp.json`을 Node 스텁에서
  Python으로 재연결.
- **JavaParser AST 백엔드**: `mcp/javaparser-cli/`(symbol-solver 3.28.2). `mvn -q -DskipTests package`로
  `astcli-1.0.0-shaded.jar` 생성. jar 부재 시 순수 Python 정규식 fallback으로 degrade.
- **near-100% 커버리지 게이트**: JaCoCo(LINE≥0.95 / BRANCH≥0.90 / METHOD≥0.95 / CLASS=1.00) +
  제외 allowlist. `build_test_server`에 `parse_jacoco_report`, `coverage_gate` 추가.
- **뮤테이션 테스트**: PITest(mutationThreshold 0.80). `parse_pitest_report` 추가.
- **신규 에이전트 2종**: `coverage-closer`(미커버 gap 닫기), `mutation-analyst`(survivor 제거).
- **신규 스킬 3종**: `configure-harness`(AskUserQuestion 인터랙티브 설정), `measure-coverage`,
  `mutation-test`. `full-pipeline`에 0단계(설정)·8단계(커버리지 루프)·9단계(뮤테이션 루프) 통합.
- **인터랙티브 인터뷰 4항목**: 스펙 경로 추가 / 대상 폴더·패키지 선별 / 뮤테이션 깊이·대상 /
  커버리지 임계값·제외. 비대화형(CI)에서는 기본값으로 스킵.
- **빌드/CI 게이트**: `examples/gradle/build.gradle.kts`·`examples/maven/pom-snippet.xml`에 JaCoCo+PITest,
  CI는 `check`/`verify`로 게이트 강제 + jacoco/pitest 리포트 artifact 업로드.
- **패키징**: `mcp/requirements.txt`, `mcp/pyproject.toml`(mcp[cli]). `RESEARCH_NOTES.md` 추가.

### Changed

- `plugin.json` 0.1.0 → 0.2.0, 설명에 설정·커버리지·뮤테이션 단계 반영.
- `scripts/*-server.js`(Node MCP 스텁) 제거 — Python 구현으로 대체.

### Notes

- AskUserQuestion 인터뷰는 interactive CLI에서만 의미. `claude -p`/CI에서는 인터뷰를 건너뛴다.
- 커버리지 100%는 제외 allowlist를 둔 **near-100%** 정책이며 임의 제외는 금지(설정/사용자 확인 필요).

---

## [0.1.0] - 2026-06-24

### Added

- **plugin 구조**: `.claude-plugin/plugin.json` manifest, `settings.json` 권한 기본값.
- **Skills 8종**: `full-pipeline`, `ingest-specs`, `analyze-ast`, `analyze-source`,
  `generate-scenarios`, `generate-tests`, `run-tests`, `repair-tests`.
- **Agents 7종**: `ast-structure-analyzer`, `source-code-analyzer`, `spec-reviewer`,
  `scenario-generator`, `test-code-generator`, `test-runner`, `test-fixer`.
  read-only / write / execute 권한을 에이전트별로 분리.
- **MCP 서버 3종**: `repo-ast-mcp`(JavaParser 기반 AST), `spec-doc-mcp`(스펙 문서),
  `build-test-mcp`(빌드 도구·테스트 실행·JUnit XML 파싱). 모두 stdio transport.
- **보안 기본값**: 네트워크 차단, 경로 allowlist, 민감정보 redaction(`scripts/redact-secrets.py`),
  hooks 보수적 설정(`hooks/hooks.json`).
- **스크립트**: `detect-build-tool.sh`, `run-tests.sh`, `collect-test-reports.py`,
  `redact-secrets.py`, `postprocess-report.py`.
- **예제 파일**:
  - `examples/java/OrderControllerTest.java`: `@WebMvcTest` + `MockMvc` + `@MockitoBean` 슬라이스 테스트.
    `org.springframework.test.context.bean.override.mockito.MockitoBean` 최신 import 사용.
  - `examples/java/OrderAmountCalculatorTest.java`: 순수 단위 테스트 + `@ParameterizedTest` `@CsvSource`.
  - `examples/json/scenario-example.json`: ScenarioSet JSON (4개 시나리오).
  - `examples/json/test-run-result.json`: TestRunResult JSON (TEST_RUNTIME_FAILED 포함).
  - `examples/json/repair-example.md`: 실패→최소 diff 보정 서술 (한국어).
  - `examples/gradle/build.gradle.kts`: Spring Boot 4.1.0, `useJUnitPlatform()`, `maxParallelForks=2`.
  - `examples/maven/pom-snippet.xml`: `maven-compiler-plugin` `<release>17</release>`,
    `maven-surefire-plugin` + Failsafe 분리 안내 주석.
  - `examples/ci/gradle-ci.yml`: GitHub Actions, `setup-java@v5` temurin 17, `cache: gradle`,
    `cache-dependency-path`, `upload-artifact`, 조건부 `upload-sarif`.
  - `examples/ci/maven-ci.yml`: 동일 구조의 Maven 버전.

### JUnit 버전 정책 — BOM 기본값과의 편차 명시

> **`strict-5x` 정책은 Boot 4.1.0 BOM 기본값과 충돌한다. 이 항목을 반드시 숙지할 것.**

Spring Boot 4.1.0 BOM은 **JUnit Jupiter/Platform 6.0.x**를 기본으로 관리한다.
사용자가 "JUnit 5"를 API 스타일 의미로 사용하는 경우(Jupiter API 사용 관용구)와
숫자 5.x 버전으로 고정하는 경우를 구분해야 한다.

| 정책 | 동작 | 비고 |
|---|---|---|
| `jupiter-style` (기본) | BOM이 관리하는 Jupiter 6.0.x 사용 | 권장. BOM 업그레이드 시 자동 추적 |
| `strict-5x` (옵트인) | `junit.version` 프로퍼티로 5.x 강제 다운핀 | **정책 예외**. 아래 절차 필수 |

`strict-5x` 적용 시 필수 절차:

1. `build.gradle.kts`에 `extra["junit.version"] = "5.11.4"` 등 명시적 버전 핀 추가.
2. `mvn dependency:tree` 또는 `./gradlew dependencies`로 실제 resolved 버전 확인.
3. 이 CHANGELOG에 핀 이유·날짜·담당자를 기록.
4. Spring Boot BOM 업그레이드 시 충돌 여부 재검토 필수.

**이 플러그인의 모든 예제 코드와 빌드 설정은 `jupiter-style`(BOM 위임) 기준으로 작성되었다.**

[Unreleased]: https://github.com/example/spring-test-harness-plugin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/example/spring-test-harness-plugin/releases/tag/v0.1.0
