# RESEARCH_NOTES — 핀 고정된 공식 버전/API (2026-06-25 검증)

> 모든 구현은 이 문서를 단일 진실 소스로 삼는다. 값은 웹검색으로 확인한 공식 출처 기반이며, 빌드 시점에 프로젝트의 resolved BOM/플러그인 카탈로그로 재확인할 것.

## 1. MCP Python SDK (서버 구현 표준)
- 패키지: **`mcp`** (CLI 추가기능 포함 시 `mcp[cli]`). 공식: [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- 최소 런타임: **Python 3.10+**
- 고수준 API: **FastMCP** — `from mcp.server.fastmcp import FastMCP`
- 노출 컴포넌트: **tools**(부수효과/POST 유사), **resources**(컨텍스트 로드/GET 유사), **prompts**(재사용 템플릿)
- transport: **stdio**(로컬 기본), SSE(폐지 예정), Streamable HTTP(원격 권장)
- 구현 패턴:
  ```python
  from mcp.server.fastmcp import FastMCP
  mcp = FastMCP("repo-ast")

  @mcp.tool()
  def extract_test_targets(paths: list[str], kinds: list[str] | None = None) -> dict:
      """대상 패키지/파일에서 테스트 대상 후보를 추출한다."""
      ...

  @mcp.resource("ast://index")
  def ast_index() -> str: ...

  @mcp.prompt()
  def explain_target_shape(fqcn: str) -> str: ...

  if __name__ == "__main__":
      mcp.run(transport="stdio")
  ```
- `.mcp.json` 연결: `command: "python3"`, `args: ["${CLAUDE_PLUGIN_ROOT}/mcp/<server>.py"]` 또는 콘솔 엔트리포인트.

## 2. Java AST: JavaParser + Symbol Solver
- 좌표: `com.github.javaparser:javaparser-symbol-solver-core:**3.28.2**` (AST + symbol resolution 통합). 공식: [javaparser.org](https://javaparser.org/), [mvnrepository](https://mvnrepository.com/artifact/com.github.javaparser/javaparser-symbol-solver-core)
- Java 1–25 파싱 지원.
- 전략: 번들 **JavaParser CLI(Java helper jar)** 를 `subprocess`로 호출해 JSON(AST 메타/심볼) 반환 → Python FastMCP 서버가 래핑. JDK/jar 미가용 시 **순수 Python 휴리스틱(정규식 기반 시그니처 추출)** 으로 degrade하고 `unresolvedSymbols`/`degraded:true` 표기.
- 보안: 코드 본문 미반환(노드/시그니처/애노테이션 메타만), 프로젝트 루트 내부 경로 allowlist.

## 3. 커버리지: JaCoCo
- 버전: **0.8.12** (Java 17+ 정상 동작). 공식: [JaCoCo Gradle Plugin](https://docs.gradle.org/current/userguide/jacoco_plugin.html), [DSL: JacocoCoverageVerification](https://docs.gradle.org/current/dsl/org.gradle.testing.jacoco.tasks.JacocoCoverageVerification.html)
- 카운터: **LINE, BRANCH, METHOD, CLASS**, INSTRUCTION, COMPLEXITY. 우리는 LINE/BRANCH/METHOD/CLASS 4종 게이트.
- Gradle: `jacocoTestReport`(리포트, XML/HTML) + `jacocoTestCoverageVerification`(게이트). `violationRules { rule { limit { counter='BRANCH'; value='COVEREDRATIO'; minimum=0.90 } } }`. `check.dependsOn(jacocoTestCoverageVerification)`.
- Maven: `org.jacoco:jacoco-maven-plugin:0.8.12`, goals `prepare-agent` + `report` + **`check`**(rule가 위반되면 빌드 실패). XML 리포트 위치: `target/site/jacoco/jacoco.xml`.
- 제외 allowlist: 생성코드/DTO/config/`*Application` 등은 `excludes`로 제외(near-100% 현실화).

## 4. 뮤테이션: PITest
- Gradle: **`info.solidsoft.pitest` 1.19.0**, `pitest { junit5PluginVersion = "1.0.0" }`. 공식: [gradle-pitest-plugin](https://gradle-pitest-plugin.solidsoft.info/), [szpak/gradle-pitest-plugin](https://github.com/szpak/gradle-pitest-plugin)
- Maven: `org.pitest:pitest-maven` + `org.pitest:pitest-junit5-plugin`.
- 핵심 옵션: `targetClasses`, `targetTests`, `mutators`(기본/STRONGER), `mutationThreshold`, `threads`, `timestampedReports=false`, `withHistory=true`(증분). 리포트: `build/reports/pitest/`.
- JUnit5 지원: `pitest-junit5-plugin **1.0.0+**` (PIT 1.9.0+ 요구). 공식: [pitest/pitest-junit5-plugin](https://github.com/pitest/pitest-junit5-plugin)
- 해석: line/branch 100%여도 살아남은 mutant가 있으면 **assertion 부재/약함** → mutation-analyst가 테스트 강화.

## 5. Spring 최신 테스트 API (Boot 4.1.0)
- Boot 4.1.0 / Framework 7.0.8+ / Java 17–26 / Gradle 8.14+(9.x) / Maven 3.6.3+. 공식: [System Requirements](https://docs.spring.io/spring-boot/system-requirements.html)
- BOM 관리: JUnit Jupiter/Platform **6.0.x**, Mockito **5.2x** (정확 patch는 resolved BOM에서 확인). 공식: [Dependency Versions](https://docs.spring.io/spring-boot/appendix/dependency-versions/index.html)
- 슬라이스/관용구 (공식: [Testing Spring Boot Applications](https://docs.spring.io/spring-boot/reference/testing/spring-boot-applications.html)):
  - `@WebMvcTest(Xxx.class)` → MVC auto-config + **MockMvc** 자동 구성. 협력 빈은 `@MockitoBean`.
  - `@DataJpaTest` → JPA 슬라이스, in-memory DB 기본(`@AutoConfigureTestDatabase`로 제어).
  - `@MockitoBean` = Spring Framework 어노테이션(구 `@MockBean` 대체). import: `org.springframework.test.context.bean.override.mockito.MockitoBean`.
  - `@SpringBootTest` = full context, 꼭 필요할 때만.
  - 테스트 한정 프로퍼티: `@TestPropertySource`.
- JUnit 정책: **jupiter-style 기본**(버전은 BOM 위임). `strict-5x`는 정책 예외(별도 pin + 경고).

## 6. near-100% 커버리지 정책(현실화)
- 목표 게이트(기본, 런타임 조정 가능): LINE ≥ 0.95, BRANCH ≥ 0.90, METHOD ≥ 0.95, CLASS ≥ 1.00, mutationThreshold ≥ 0.80.
- 제외 allowlist(기본 제안): `**/*Application*`, `**/config/**`, `**/dto/**`, `**/generated/**`, lombok/MapStruct 생성물, `equals/hashCode/toString` 자동생성.
- 게이트 미달 시: coverage-closer/mutation-analyst가 gap을 받아 추가 테스트 생성 → 재측정 루프.

## 7. 런타임 인터뷰(AskUserQuestion) 항목 — 4종 전부 채택
1. 스펙 문서 경로 추가 입력 → spec-doc.index_docs
2. 테스트 생성 대상 폴더/패키지/클래스 선별 → 대상 스코프 한정
3. 뮤테이션 테스트 깊이/대상(mutators 세트, targetClasses, mutationThreshold)
4. 커버리지 임계값 + 제외 규칙(allowlist)
- 제약: AskUserQuestion은 **interactive CLI에서만** 의미. 비대화형/CI(`claude -p`)에서는 HarnessRequest JSON + 기본값으로 대체(=인터뷰 스킵).
