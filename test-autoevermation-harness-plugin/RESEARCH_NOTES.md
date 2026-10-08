# RESEARCH_NOTES — 핀 고정된 공식 버전/API (2026-06-25 검증)


## 0. Codex 0.35.0 구현 근거 (2026-10-08)

조사 순서: 루트 카탈로그 → 플러그인 매니페스트·MCP/LSP/훅 → 공용 런처·bootstrap → MCP 3종과 JavaParser CLI → 15개 스킬·11개 역할 및 참조 계약 → 설치/운영 문서·기존 검사. 핵심 연결은 `full-pipeline → configure-harness/분석/생성/실행 스킬 → 역할 지침 → repo-ast/spec-doc/build-test`다. 호스트별 실행 차이만 어댑터로 분리하고 산출물 v2를 재사용한다.

| 읽은 파일·심볼 | 공식 근거 | 확인 버전 | 적용 결정 |
|---|---|---|---|
| `.claude-plugin/plugin.json`, root `plugin.json`, `mcp.json`, `.agents/plugins/marketplace.json` | [패키징](https://developers.openai.com/plugins/build/plugins), [plugin schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json), [MCP schema](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json) | Agent Plugins schema 1.0.0; Codex 0.162.0-alpha.2 | portable 구성을 추가하고 Claude 구성 유지, 양쪽 배포 버전 0.35.0; Codex hooks 빈 객체 |
| `launch.cjs`, `bootstrap.data_dir`, `repo_ast._request_root`, `spec_doc._snapshot` | [Codex agent_plugin_config.rs](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/agent_plugin_config.rs) | 2026-10-08 공식 main 구현 | portable stdio cwd는 PLUGIN_ROOT; PLUGIN_ROOT/DATA는 호스트 주입. 프로젝트는 명시 절대 root; 데이터 경로 별도 |
| `skills/*/SKILL.md`, `agents/*.md`, 호스트 참조 | [스킬 작성](https://developers.openai.com/plugins/build/skills), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [Claude 플러그인](https://code.claude.com/docs/en/plugins-reference) | 당일 문서; 기존 schemaVersion 2 | 공용 계약 유지, 실제 호스트 도구로 치환; 전역 에이전트 설정 설치 없음 |
| `references/evidence-workflow.md`, 저장소 `AGENTS.md` | [Superpowers workflow](https://github.com/obra/superpowers#the-basic-workflow) | Superpowers 6.4.2 | 읽기·공식 근거·TODO·원인 분석·완료 전 검증만 내장. 의무 TDD/mutation/메타 테스트·중복 승인 제외 |
| `repo_ast._request_root`, `spec_doc._request_root`, `build_test._project_root` | [pathlib](https://docs.python.org/3/library/pathlib.html) | 지원 Python 3.10+; 실행 3.14 | Windows 드라이브 없는 rooted path도 거부하도록 Path.is_absolute; resolve/상대 경계 확인 |
| `build_test._launcher`, `_output_tail`, `_run_subprocess` | [subprocess](https://docs.python.org/3/library/subprocess.html), [shutil.which](https://docs.python.org/3/library/shutil.html#shutil.which), [Node spawn](https://nodejs.org/api/child_process.html#child_processspawncommand-args-options) | Python 3.14/Node 설치 런타임 | Windows PATH 배치 런처 절대 경로화. Python 자식 UTF-8, Java/cmd 출력은 바이트 수신 후 UTF-8/Windows ANSI 해석 |
| `build_test._project_root`의 오류 전달 | [SDK ToolError](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/mcpserver/exceptions.py) | SDK 2.3.0, 기존 범위 >=2.2,<3 | 예상 root 오류를 ToolError로 전달; 일반 ValueError는 SDK가 세부 내용을 숨김 |
| `mcp/javaparser-cli/pom.xml`, `persist_astcli_jar.data_dir` | [JavaParser 공식 저장소](https://github.com/javaparser/javaparser), 로컬 pom release 17 | JavaParser 3.28.2, compiler release 17 | 의존성 유지. Codex는 JDK17+ AST, Claude는 JDT LS 때문에 기존 JDK21+ 유지 |
| 설치 캐시·스킬/MCP 노출 | [app-server](https://learn.chatgpt.com/docs/app-server), 설치된 `codex plugin --help` | Codex 0.162.0-alpha.2 | CLI 실제 설치, 앱 서버 skills/list·mcpServerStatus/list로 확인. GUI E2E와 구분 |

실행 TODO와 결과:

- [x] portable 패키지·로컬/Git 카탈로그 구성 및 0.35.0 버전 정렬.
- [x] 영속 경로·UTF-8·명시 root·스펙 root 격리 구현, 공용 MCP 호환 유지.
- [x] 스킬/역할 호스트 라우팅과 Codex의 LSP/훅 없는 실행 계약 적용.
- [x] 공통 조사·TODO·디버깅·최신 검증 정책 내장; 자체 테스트 파일 무변경.
- [x] 설치 가이드·호스트 차이·변경 이력 및 실제 검증 기록 정리.
- [x] 기존 검사·실제 stdio·Codex 설치/app-server·기존 Gradle/Maven 통합 실행.
- [ ] 데스크톱 GUI 클릭 설치와 실제 대화형 전체 파이프라인: 이 세션에서는 미실행.
- [ ] 원격 Git 설치: 변경 push 후 확인 필요. 이번 작업에서 게시하지 않음.

구현 조사와 검증에서 확인된 환경 제한은 [docs/codex-validation.md](docs/codex-validation.md)에 기록한다. 이 절은 Codex 추가 범위의 근거이며 아래 기존 Spring/JUnit/JaCoCo 버전 정책을 변경하지 않는다.

> 모든 구현은 이 문서를 단일 진실 소스로 삼는다. 값은 웹검색으로 확인한 공식 출처 기반이며, 빌드 시점에 프로젝트의 resolved BOM/플러그인 카탈로그로 재확인할 것.

## 1. MCP Python SDK (서버 구현 표준)
- 패키지: **`mcp`** (CLI 추가기능 포함 시 `mcp[cli]`). 공식: [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- 최소 런타임: **Python 3.10+**
- 고수준 API: **MCPServer** — `from mcp.server.mcpserver import MCPServer`
- SDK가 노출할 수 있는 컴포넌트: **tools**(부수효과/POST 유사), **resources**(컨텍스트 로드/GET 유사), **prompts**(재사용 템플릿)
- transport: **stdio**(로컬 기본), SSE(폐지 예정), Streamable HTTP(원격 권장)
- 구현 패턴:
  ```python
  from mcp.server.mcpserver import MCPServer
  mcp = MCPServer("repo-ast")

  @mcp.tool()
  def extract_test_targets(paths: list[str], kinds: list[str] | None = None) -> dict:
      """대상 패키지/파일에서 테스트 대상 후보를 추출한다."""
      ...

  if __name__ == "__main__":
      mcp.run(transport="stdio")
  ```

> ⚠️ **이 프로젝트는 의도적으로 `@mcp.tool()`만 노출한다. resource·prompt를 추가하지 말 것.**
> 위 "SDK가 노출할 수 있는 3종"은 SDK 능력 설명이지 이 하네스의 요구사항이 아니다. 이 문서의 초판
> 스니펫에는 `@mcp.resource("ast://index")` / `@mcp.prompt() explain_target_shape(...)` 예시가
> 들어 있었고, 그 **예시 이름 그대로** 서버 3종에 리소스 4종·프롬프트 3종이 구현됐다. 이후
> **45커밋·32릴리스 동안 한 번도 수정되지 않았고 CHANGELOG 언급 0회**였다 — 소비자가 없었기 때문이다.
> 파이프라인 에이전트 11개의 도구 목록에는 `ReadMcpResourceTool`이 없어 **리소스·프롬프트는 구조적으로
> 호출 불가**하고, 사용자만 `@`멘션·`/mcp__server__prompt`로 닿을 수 있다. 그 결과 검증도 갱신도 받지
> 않은 채 실제 계약에서 드리프트해 틀린 안내를 하게 됐다(무조건 `--offline` vs 실제
> `BUILD_TEST_ALLOW_NETWORK` 분기; 무조건 `@MockitoBean` vs Boot ≤3.3 `@MockBean` — §8).
> **v0.33.0에서 7종 전부 삭제.** 새 기능은 tool로 추가하고, 재사용 프롬프트는 `agents/*.md`에 둔다.
- `.mcp.json` 연결: `command: "node"`, `args: ["${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs", "${CLAUDE_PLUGIN_ROOT}/mcp/<server>.py"]` — `launch.cjs`가 `${CLAUDE_PLUGIN_DATA}`의 venv를 프로비저닝한 뒤 서버를 실행한다(v0.28.0).

## 2. Java AST: JavaParser + Symbol Solver
- 좌표: `com.github.javaparser:javaparser-symbol-solver-core:**3.28.2**` (AST + symbol resolution 통합). 공식: [javaparser.org](https://javaparser.org/), [mvnrepository](https://mvnrepository.com/artifact/com.github.javaparser/javaparser-symbol-solver-core)
- Java 1–25 파싱 지원.
- 전략: 번들 **JavaParser CLI(Java helper jar)** 를 `subprocess`로 호출해 JSON(AST 메타/심볼) 반환 → Python MCPServer 서버가 래핑.
- **JavaParser 필수(v0.16.0~)**: 플러그인 배포는 `.mcp.json`이 `REPO_AST_REQUIRE_JAVAPARSER=1`을 기본 설정하므로 jar/JDK 미가용 시 `status:"failed"`(`JAVAPARSER_REQUIRED`)로 **하드 실패**한다(fallback-policy.md #2/#20). 정규식 기반 휴리스틱 경로는 **v0.31.0에서 삭제**됐다 — 플래그 미설정 standalone 사용에서도 대체 경로가 없다. `degraded:true`는 이제 "JavaParser가 일부 파일을 못 읽어 결과에서 뺐다"는 신호이며 `warnings`에 해당 파일명이 실린다.
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
> 하네스는 대상 프로젝트의 **`springProfile`** 을 감지(`build-test-mcp.detect_spring_profile`)하거나 인터뷰로 받아, 아래 4개 축의 관용구를 분기 선택한다. 감지 실패 시 인터뷰(대화형) 또는 비대화형은 `HarnessRequest.springVersion` 필수 — 가정 금지, 미지정 시 `status:"failed"`(fallback-policy #4). 출처: [Boot 2.x System Requirements](https://docs.spring.io/spring-boot/docs/2.7.x/reference/html/getting-started.html#getting-started-system-requirements), [Boot 3.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide), [@MockitoBean(6.2)](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/test/context/bean/override/mockito/MockitoBean.html), [@MockBean(deprecated 3.4)](https://docs.spring.io/spring-boot/3.5/api/java/org/springframework/boot/test/mock/mockito/MockBean.html).

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
- 제약: AskUserQuestion은 **대화형 세션에서만** 호출 가능(비대화형 판정은 configure-harness 「인터랙티브 모드 감지」). 비대화형에서는 인터뷰를 건너뛰고 HarnessRequest JSON으로 구성하되, #13 필수 항목이 비면 하드 중단(임의 기본값 금지; 문서화된 기본값이 있는 커버리지 임계값·제외만 기본값 사용).
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
