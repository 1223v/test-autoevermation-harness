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
- 전략: 번들 **JavaParser CLI(Java helper jar)** 를 `subprocess`로 호출해 JSON(AST 메타/심볼) 반환 → Python FastMCP 서버가 래핑.
- **JavaParser 필수(v0.16.0~)**: 플러그인 배포는 `.mcp.json`이 `REPO_AST_REQUIRE_JAVAPARSER=1`을 기본 설정하므로 jar/JDK 미가용 시 `status:"failed"`(`JAVAPARSER_REQUIRED`)로 **하드 실패**한다(fallback-policy.md #2/#20). 정규식 기반 휴리스틱 경로(`degraded:true`)는 **standalone 서버 단독 사용**(플래그 미설정) 시 코드 기본값으로만 잔존하며, 파이프라인 경로에서는 쓰이지 않는다.
- 보안: 코드 본문·호출 인자 미반환(노드/시그니처/애노테이션/호출 메서드 **이름** 메타만 — v0.17.0 `invokedMethods`/`methodCalls`), 프로젝트 루트 내부 경로 allowlist(`REPO_AST_ALLOW_ROOT`).

## 3. 커버리지: JaCoCo
- 버전: **0.8.12** (Java 17+ 정상 동작). 공식: [JaCoCo Gradle Plugin](https://docs.gradle.org/current/userguide/jacoco_plugin.html), [DSL: JacocoCoverageVerification](https://docs.gradle.org/current/dsl/org.gradle.testing.jacoco.tasks.JacocoCoverageVerification.html)
- 카운터: **LINE, BRANCH, METHOD, CLASS**, INSTRUCTION, COMPLEXITY. 우리는 LINE/BRANCH/METHOD/CLASS 4종 게이트.
- Gradle: `jacocoTestReport`(리포트, XML/HTML) + `jacocoTestCoverageVerification`(게이트). `violationRules { rule { limit { counter='BRANCH'; value='COVEREDRATIO'; minimum=0.90 } } }`. `check.dependsOn(jacocoTestCoverageVerification)`.
- Maven: `org.jacoco:jacoco-maven-plugin:0.8.12`, goals `prepare-agent` + `report` + **`check`**(rule가 위반되면 빌드 실패). XML 리포트 위치: `target/site/jacoco/jacoco.xml`.
- 제외 allowlist: 생성코드/DTO/config/`*Application` 등은 `excludes`로 제외(near-100% 현실화).

## 5. Spring 최신 테스트 API (Boot 4.1.0 = "latest" 프로파일)
- Boot 4.1.0 / Framework 7.0.8+ / Java 17–26 / Gradle 8.14+(9.x) / Maven 3.6.3+. 공식: [System Requirements](https://docs.spring.io/spring-boot/system-requirements.html)
- BOM 관리: JUnit Jupiter/Platform **6.0.x**, Mockito **5.2x** (정확 patch는 resolved BOM에서 확인). 공식: [Dependency Versions](https://docs.spring.io/spring-boot/appendix/dependency-versions/index.html)
- 슬라이스/관용구 (공식: [Testing Spring Boot Applications](https://docs.spring.io/spring-boot/reference/testing/spring-boot-applications.html)):
  - `@WebMvcTest(Xxx.class)` → MVC auto-config + **MockMvc** 자동 구성. 협력 빈은 `@MockitoBean`.
  - `@DataJpaTest` → JPA 슬라이스, in-memory DB 기본(`@AutoConfigureTestDatabase`로 제어).
  - `@MockitoBean` = Spring Framework 어노테이션(구 `@MockBean` 대체). import: `org.springframework.test.context.bean.override.mockito.MockitoBean`.
  - `@SpringBootTest` = full context, 꼭 필요할 때만.
  - 테스트 한정 프로퍼티: `@TestPropertySource`.
- JUnit 정책: **jupiter-style 기본**(버전은 BOM 위임). `strict-5x`는 정책 예외(별도 pin + 경고).

> ⚠️ 위 관용구는 **Boot 4.x("latest") 프로파일 전용**이다. Boot 2.x/3.x 대상에서는 §8의 버전별 프로파일을 따라야 컴파일된다. 전체 코드 템플릿은 [version-compatibility.md](./references/version-compatibility.md) 참조.

## 8. 버전 호환 프로파일 매트릭스 (Boot 2.0 – 4.x) — 하위호환의 단일 진실 소스
> 하네스는 대상 프로젝트의 **`springProfile`** 을 감지(`build-test-mcp.detect_spring_profile`)하거나 인터뷰로 받아, 아래 4개 축의 관용구를 분기 선택한다. 감지 실패 시 인터뷰(대화형) 또는 latest 가정(CI)+경고. 출처: [Boot 2.x System Requirements](https://docs.spring.io/spring-boot/docs/2.7.x/reference/html/getting-started.html#getting-started-system-requirements), [Boot 3.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide), [@MockitoBean(6.2)](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/test/context/bean/override/mockito/MockitoBean.html), [@MockBean(deprecated 3.4)](https://docs.spring.io/spring-boot/3.5/api/java/org/springframework/boot/test/mock/mockito/MockBean.html).

| Boot | Framework | Java(min) | 네임스페이스 | JUnit 기본 | Mock 애노테이션 | Mock import |
|---|---|---|---|---|---|---|
| 2.0–2.1 | 5.0–5.1 | **8** | `javax.*` | **JUnit 4**(Vintage) | `@MockBean` | `org.springframework.boot.test.mock.mockito.MockBean` |
| 2.2–2.3 | 5.2 | 8 | `javax.*` | JUnit 5(Vintage 제외) | `@MockBean` | (동일) |
| 2.4–2.7 | 5.3 | 8(≤17) | `javax.*` | JUnit 5(Vintage 제거) | `@MockBean` | (동일) |
| 3.0–3.3 | 6.0–6.1 | **17** | `jakarta.*` | JUnit 5 | `@MockBean` | (동일) |
| 3.4–3.x | 6.2 | 17 | `jakarta.*` | JUnit 5 | `@MockitoBean`(권장) | `org.springframework.test.context.bean.override.mockito.MockitoBean` |
| 4.x | 7.x | 17 | `jakarta.*` | JUnit 5/6 | `@MockitoBean`(필수, `@MockBean` 제거) | (동일) |

**4개 분기 축**
1. **네임스페이스**: Boot 2.x = `javax.persistence/validation/servlet`, Boot 3.x+ = `jakarta.*`. 생성 코드 import·엔티티 참조에 직접 영향.
2. **JUnit 엔진**: `junit4`(=`@RunWith(SpringRunner.class)`+`org.junit.Test`, `@DisplayName` 없음) vs `jupiter`(`@ExtendWith`/`@Test`+`@DisplayName`). 2.0–2.1 기본 junit4; 2.2+ jupiter. 단 프로젝트가 vintage/junit:junit을 쓰면 junit4 유지.
3. **Mock 애노테이션**: Boot ≤3.3 = `@MockBean`(boot.test.mock.mockito), 3.4+ = `@MockitoBean`(test.context.bean.override.mockito). 4.0에서 `@MockBean` 제거.
4. **빌드/툴 베이스라인**: Java 8(2.x)/17(3.x+); Gradle `useJUnit()`(순수 junit4) vs `useJUnitPlatform()`; JaCoCo 버전 폴백(§아래).

**JaCoCo 버전 폴백** (Java 베이스라인별)
- JaCoCo: **0.8.12**는 Java 8 런타임에서도 정상(바이트코드 5–23 지원). 매우 오래된 Gradle(≤6.x)이면 `toolVersion`만 0.8.8+로 낮춰도 됨. 공식: [JaCoCo Releases](https://www.jacoco.org/jacoco/trunk/doc/changes.html)

## 6. near-100% 커버리지 정책(현실화)
- 목표 게이트(기본, 런타임 조정 가능): LINE ≥ 0.95, BRANCH ≥ 0.90, METHOD ≥ 0.95, CLASS ≥ 1.00.
- 제외 allowlist(기본 제안): `**/*Application*`, `**/config/**`, `**/dto/**`, `**/generated/**`, lombok/MapStruct 생성물, `equals/hashCode/toString` 자동생성.
- 게이트 미달 시: coverage-closer가 gap을 받아 추가 테스트 생성 → 재측정 루프.

## 7. 런타임 인터뷰(AskUserQuestion) 항목 — 3종 전부 채택
1. 스펙 문서 경로 추가 입력 → spec-doc.index_docs
2. 테스트 생성 대상 폴더/패키지/클래스 선별 → 대상 스코프 한정
3. 커버리지 임계값 + 제외 규칙(allowlist)
- 제약: AskUserQuestion은 **interactive CLI에서만** 의미. 비대화형/CI(`claude -p`)에서는 HarnessRequest JSON + 기본값으로 대체(=인터뷰 스킵).
- 3.5단계 리팩토링 권고 게이트(#19)의 포함/제외 질문은 인터뷰 3종과 별개의 **파이프라인 중간 게이트**이며 `HarnessConfig.refactorAdvisory`는 인터뷰 항목이 아니다(비침습 기본값).

## 9. 리팩토링 권고 게이트(3.5단계) 기준 근거 — 공식/1차 문서 (2026-07-02 검증)

탐지 기준·임계값·게이트 의미론의 정본은 [references/refactor-advisory.md](./references/refactor-advisory.md). 여기에는 출처만 핀 고정한다.

- **순환복잡도 임계 10 (11–15 medium / >15 high)**: NIST SP 500-235 *Structured Testing: A Testing Methodology
  Using the Cyclomatic Complexity Metric* — <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf>.
  McCabe 원 한도 10은 "유의미한 근거가 축적된 출발점"; 15까지 상향은 숙련 인력·정형 설계·추가 테스트 노력 전제.
  structured testing에서 복잡도 = 검증에 필요한 기본 경로(basis path) 테스트 수.
- **생성자 주입·DI 테스트 용이성**: Spring Framework 공식 레퍼런스 (Core > Dependency Injection) —
  <https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html>.
  "The Spring team generally advocates constructor injection"; DI로 "your classes become easier to test …
  stub or mock implementations"; "a large number of constructor arguments is a bad code smell … too many
  responsibilities and should be refactored"(→ `constructorArgs` 임계 근거).
- **static/final mock 제약**: Mockito 공식 javadoc — <https://javadoc.io/doc/org.mockito/mockito-core/latest/org/mockito/Mockito.html>.
  §39 final 타입 mock: inline mock maker는 **5.0.0부터 기본**(이전 버전은 mockito-inline 별도 필요 → Boot 2.x
  프로파일에서 static/final mock 제약). §48 static mock: 현재 스레드 한정 + try-with-resources 스코프 필수.
- **테스트 저해 설계 4대 flaw**: Google Testing Blog — *Guide to Writing Testable Code* —
  <https://testing.googleblog.com/2008/11/guide-to-writing-testable-code.html>.
  Constructor does Real Work / Digging into Collaborators(train wreck) / Brittle Global State & Singletons
  ("Global state is the enemy of testing") / Class Does Too Much.
- **N+1·fetch 전략**: Hibernate ORM 공식 User Guide, Fetching 장 —
  <https://docs.hibernate.org/orm/5.2/userguide/html_single/chapters/fetching/Fetching.html>
  (현행판: <https://docs.jboss.org/hibernate/orm/6.6/userguide/html_single/Hibernate_User_Guide.html#fetching>).
  "the strategy generally termed N+1"; "you should prefer LAZY associations"; 해법 JOIN FETCH·entity graph·
  `@BatchSize`("a DTO projection or a JOIN FETCH is a much better alternative").
