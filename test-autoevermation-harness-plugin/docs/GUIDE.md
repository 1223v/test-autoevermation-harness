# Spring 테스트 하네스 — 동작 원리·사용 가이드 (GUIDE)

이 문서는 `test-autoevermation-harness-plugin` 플러그인이 **어떤 구조로, 어떤 순서로 동작하는지**와
**설치부터 실행·설정·산출물 해석까지 어떻게 사용하는지**를 한 곳에 정리한 종합 가이드다.

- 빠른 개요·표 위주 요약: [README.md](../README.md)
- 흐름 다이어그램(Mermaid): [pipeline-flow.md](./pipeline-flow.md)
- 단계·정책의 정본(SSOT): [skills/full-pipeline/SKILL.md](../skills/full-pipeline/SKILL.md) · [references/](../references/)
- 핀 고정된 버전·API 근거: [RESEARCH_NOTES.md](../RESEARCH_NOTES.md)

> 사실 확인: 이 문서의 Claude Code 플러그인 시스템 서술은 공식 문서
> ([Plugins reference](https://code.claude.com/docs/en/plugins-reference), [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)),
> MCP 서버 서술은 [공식 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)로 2026-07-02 재검증했다.

---

## 목차

1. [개요 — 무엇을 하는 플러그인인가](#1-개요)
2. [아키텍처 — 구성요소 지도](#2-아키텍처)
3. [동작 방식 — 파이프라인 단계별 상세](#3-동작-방식)
4. [설치](#4-설치)
5. [사용법](#5-사용법)
6. [설정 — HarnessRequest·HarnessConfig·환경변수](#6-설정)
7. [산출물 해석](#7-산출물)
8. [보안 모델](#8-보안-모델)
9. [트러블슈팅](#9-트러블슈팅)
10. [문서 지도](#10-문서-지도)

---

## 1. 개요

**Spring 프로젝트에 테스트 코드를 자동으로 생성·검증하는 Claude Code 플러그인**이다.
명령 하나(`/test-autoevermation-harness-plugin:full-pipeline`)로 아래 전 과정을 오케스트레이션한다.

```
스펙 문서 인덱싱 ─┐
                  ├→ 소스 분석 → 리팩토링 권고 게이트 → 시나리오 설계 → 사용자 승인
AST 구조 추출  ───┘                                                        │
                                                                           ▼
   시나리오 적합성 검증 ← 뮤테이션 강화 ← 커버리지 게이트 ← 실패 보정 ← 실행 ← 테스트 생성
```

핵심 특성:

- **버전 인식(Boot 2.0–4.x)**: 대상 프로젝트의 Spring Boot 버전 프로파일을 감지해
  `javax`/`jakarta` 네임스페이스, JUnit4/Jupiter 엔진, `@MockBean`/`@MockitoBean`을 자동 분기한다.
  컴파일되는 테스트를 만들기 위한 전제이며, 매트릭스 정본은 [RESEARCH_NOTES §8](../RESEARCH_NOTES.md).
- **BDD living documentation**: 시나리오는 given/when/then 구조로 설계되고, 테스트 메서드명에
  `scenarioRef`(`SC-001` → `sc001_…`)가 박히며, 결과가 대상 프로젝트의 `test_docs/`에
  시나리오↔테스트코드↔결과 매핑으로 영속화된다.
- **게이트 3종**: ① 3.5단계 리팩토링 권고(테스트 부적합 코드 선별), ② 4.5단계 시나리오 승인(승인분만 생성),
  ③ 10단계 적합성 검증(통과한 테스트가 시나리오를 실제로 만족하는지). 대화형은 `AskUserQuestion`으로 묻고,
  CI는 정책에 따라 자동 진행/중단한다.
- **품질 루프 2종**: JaCoCo near-100% 커버리지 게이트(기본 LINE≥0.95/BRANCH≥0.90/METHOD≥0.95/CLASS=1.00),
  PITest 뮤테이션 강화(기본 score≥0.80). 무진전 3회 연속이면 `partial`로 정직하게 중단한다.
- **독립 실행**: oh-my-claudecode 등 외부 플러그인에 의존하지 않는다. Claude Code 네이티브 기능
  (플러그인·`Task` 서브에이전트·`AskUserQuestion`·MCP·훅)만 필수다 — Python 3.10+는 없으면
  자동 설치된다(v0.13.0+, macOS/Linux). 상세: [DEPENDENCIES.md](../DEPENDENCIES.md).

---

## 2. 아키텍처

### 2.1 구성요소 한눈에

```
test-autoevermation-harness-plugin/
├── .claude-plugin/plugin.json   ← 매니페스트: skills/·.mcp.json·.lsp.json 등록(표준 hooks/hooks.json은 자동 로드)
├── skills/        (14종)        ← /test-autoevermation-harness-plugin:<name> 명령. 절차(무엇을 어떤 순서로)의 정의
├── agents/        (11종)        ← Task(subagent_type=...)로 호출되는 서브에이전트. 실제 분석/생성 수행
├── mcp/           (서버 3종)    ← Python FastMCP stdio 서버. 결정적 작업(파싱·빌드실행·리포트 해석)
│   └── javaparser-cli/          ← JavaParser 기반 정밀 AST CLI (Maven, 선택 빌드)
├── hooks/hooks.json + scripts/  ← 네트워크 가드·경로 가드·시크릿 redaction (런타임 보안)
├── references/    (7종)         ← 정책·절차의 SSOT 문서 (스킬·에이전트가 인용)
├── docs/                        ← 이 가이드 + pipeline-flow.md(다이어그램)
└── .lsp.json                    ← (선택) Eclipse JDT LS 등록
```

역할 분담 원칙: **스킬 = 절차서**(단계·게이트·fallback 분기를 기술), **에이전트 = 실행자**(권한이
최소화된 read-only/write 분리), **MCP 서버 = 결정적 도구**(같은 입력이면 같은 출력 — 빌드 실행,
XML 파싱, 버전 감지 등 LLM에 맡기면 안 되는 부분).

### 2.2 Skills (14종)

| Skill | 파이프라인 단계 | 역할 |
|---|---|---|
| `configure-harness` | Phase E + 0/0.5/0.6 | 환경 세팅 → Spring 프로파일 감지 → 4항목 인터뷰 → `HarnessConfig` 생성 |
| `full-pipeline` | 전체 | end-to-end 오케스트레이션(아래 §3) |
| `ingest-specs` | 1 | 스펙 문서 인덱싱·acceptance criteria(Given/When/Then) 정규화 |
| `analyze-ast` | 2 | JavaParser 기반 AST 구조·테스트 대상 추출 |
| `analyze-source` | 3 | 동작·외부 I/O·mocking seam 분석 |
| `refactor-advisory` | 3.5 (판정부) | 복잡도·비효율·테스트 저해 코드 판정 (read-only) |
| `generate-scenarios` | 4 | unit/slice/integration 시나리오 설계 (BDD) |
| `generate-tests` | 5 | JUnit + Spring Test 코드 생성 (버전 프로파일 분기) |
| `run-tests` | 6 | 빌드 도구 감지 후 최소 범위 테스트 실행 |
| `repair-tests` | 7 | 실패 원인 분류 후 최소 diff 보정 |
| `measure-coverage` | 8 | JaCoCo near-100% 게이트 루프 |
| `mutation-test` | 9 | PITest 뮤테이션 강화 루프 |
| `verify-scenarios` | 10 | 시나리오 적합성 검증 + `test_docs/` 정리 |
| `setup-statusline` | (부가) | Claude Code statusLine에 Test-AutoEverMation 진행률 줄(버전·%·현재 단계) 설치/제거 |

모든 스킬은 단독 호출도 가능하다(`/test-autoevermation-harness-plugin:<skill>`). `full-pipeline`은 이들을 순서·병렬
전략에 따라 조합한다.

### 2.3 Agents (11종) — 권한 최소화

| Agent | 담당 | 권한 요지 |
|---|---|---|
| `spec-reviewer` | 1단계 | read-only + MCP(spec-doc) |
| `ast-structure-analyzer` | 2단계 | read-only + MCP(repo-ast) |
| `source-code-analyzer` | 3단계 | read-only + MCP(repo-ast, lsp) |
| `refactor-advisor` | 3.5단계 | read-only + MCP(repo-ast, lsp) — Write/Edit/Bash 불허 |
| `scenario-generator` | 4단계 | read-only + MCP(spec-doc, repo-ast) |
| `test-code-generator` | 5단계 | Read/Write/Edit + MCP(repo-ast, build-test) — Bash 없음 |
| `test-runner` | 6단계 | Read/Bash + MCP(build-test) — Write/Edit 없음 |
| `test-fixer` | 7단계 | Read/Write/Edit/Bash + MCP(all) |
| `coverage-closer` | 8단계 | Read/Write/Edit + MCP — Bash 없음 |
| `mutation-analyst` | 9단계 | Read/Write/Edit + MCP — Bash 없음 |
| `scenario-conformance-verifier` | 10단계 | Read/Write/Edit/Grep/Glob + MCP — 테스트 생성/수정 금지(문서화 전용) |

권한은 각 `agents/*.md`의 frontmatter `tools:` 목록으로 강제된다. 플러그인 배포 에이전트는
`hooks`/`mcpServers`/`permissionMode` frontmatter를 선언할 수 없다는 것이 Claude Code 공식 제약이라
([Plugins reference](https://code.claude.com/docs/en/plugins-reference)), MCP 접근은 공유 `.mcp.json` +
스킬 라우팅으로 구현한다. 모든 에이전트는 `model: inherit`라 세션 모델 그대로 동작한다(특정 티어 불필요).

### 2.4 MCP 서버 3종 (Python FastMCP, stdio)

공식 MCP Python SDK의 `FastMCP` 고수준 API(`@mcp.tool()` 데코레이터, `mcp.run(transport="stdio")`)로
구현되어 있고, `.mcp.json`이 `python3 ${CLAUDE_PLUGIN_ROOT}/mcp/<server>.py`로 기동한다.
`${CLAUDE_PLUGIN_ROOT}`(플러그인 설치 경로)·`${CLAUDE_PROJECT_DIR}`(현재 프로젝트 루트)는 Claude Code가
치환·주입하는 공식 변수다.

| 서버 | 도구 | 설명 |
|---|---|---|
| `repo-ast` | `parse_java_file` · `resolve_symbol` · `list_spring_components` · `extract_test_targets` | 구조 전용 Java AST/심볼 분석. **메서드 본문은 절대 반환하지 않음**(시그니처·애노테이션·메타만). JavaParser jar(`mcp/javaparser-cli`) 우선, 미가용 시 정규식 fallback(`degraded:true`). 커스텀 스테레오타입(`@Component` 메타 애노테이션)을 전이적으로 해석 |
| `spec-doc` | `index_docs` · `search_requirements` · `extract_acceptance_criteria` | 스펙 문서 청크 인덱싱·요구사항 검색·Given/When/Then criteria 추출. 경로 allowlist(`SPEC_DOC_ALLOWLIST`) + 민감정보 redaction |
| `build-test` | `detect_build_tool` · `detect_spring_profile` · `detect_build_capabilities` · `check_dependency_cache` · `list_test_tasks` · `run_targeted_tests` · `parse_junit_xml` · `parse_jacoco_report` · `parse_pitest_report` · `coverage_gate` | Gradle/Maven 감지, Boot 버전 프로파일 감지, 빌드 능력(JaCoCo XML·PITest) 감지, 캐시 상태 신호, 대상 한정 테스트 실행(기본 오프라인, `online=True` 1회 프라이밍 경로), 리포트 파싱, 커버리지 게이트 판정 |

각 서버는 보조 MCP 리소스(`ast://index`, `spec://glossary`, `build://metadata` 등)와 프롬프트도 노출한다.
**MCP 서버는 stdio라 사용자에게 질문할 수 없다** — 조건을 신호(`degraded`/`requiresConfirmation`/error code)로
노출만 하고, 질문/중단 판단은 스킬·에이전트 계층이 한다([fallback-policy.md](../references/fallback-policy.md) 공통규칙 3).

### 2.5 Hooks + LSP

| 훅 | 시점 | 동작 |
|---|---|---|
| `scripts/guard-network.py` | PreToolUse(Bash) | 네트워크성 명령(curl/wget 등) 차단·경고 |
| `scripts/guard-read.py` | PreToolUse(Read·WebFetch) | 시크릿(.env/pem)·vendor/build 산출물 read 차단 |
| `scripts/redact-secrets.py` | PostToolUse(Write·Edit) | 생성물의 토큰·비밀번호·접속문자열 마스킹(warn 모드) |

`settings.json`은 **권장 권한값 문서**다 — Claude Code는 플러그인 settings.json의 `permissions`/`env`를
자동 적용하지 않으므로(공식 제약), 강제는 위 훅이 담당하고 사용자는 필요 시 자기 프로젝트
`.claude/settings.json`에 복사해 쓴다.

`.lsp.json`은 Eclipse JDT LS(`jdtls`)를 선택 등록한다(Java 21+ 런타임 필요). 미설치면 `/plugin` 에러 탭
표시만 되고 AST-only로 degrade한다 — 파이프라인은 막히지 않는다.

---

## 3. 동작 방식

정본: [skills/full-pipeline/SKILL.md](../skills/full-pipeline/SKILL.md) ·
[orchestration-detail.md](../skills/full-pipeline/references/orchestration-detail.md) ·
다이어그램: [pipeline-flow.md](./pipeline-flow.md)

### 3.1 실행 모델 — 서브에이전트 팬아웃 + 파일 기반 전달

- 1·2단계(스펙 인덱싱 ∥ AST 추출)만 **병렬**(`Task` 팬아웃), 나머지는 산출물 의존이라 **순차 파이프라인**.
- 각 단계 산출물(JSON)은 메인 컨텍스트로 옮기지 않고 `_workspace/{단계}_{산출물}.json`에 저장하고
  **경로만** 다음 단계에 전달한다(컨텍스트 토큰 절감 + 감사 추적 + 부분 재실행의 기반).
- 각 서브에이전트의 `total_tokens`/`duration_ms`는 완료 시점에 `_workspace/timing.json`에 즉시 누적한다
  (병목 단계 식별용, 헬퍼: `scripts/record-timing.py`).

### 3.2 단계 흐름 (Phase E → 0 → … → 10)

| 단계 | 스킬 / 에이전트 | 하는 일 | 산출물 |
|---|---|---|---|
| **Phase E** | configure-harness | 환경 세팅 체크리스트 E1~E12를 TodoWrite로 만들어 **선제 통과**. 필수: E1 Python·E2 MCP SDK·E3 서버등록·E10 실행JDK↔Mockito. 선택(미가용 시 degrade): E4~E6 JavaParser jar, E7 JDT LS. 미충족이면 파이프라인 **미시작** | — |
| **0** | configure-harness | 4항목 인터뷰(스펙 경로/대상 선별/뮤테이션/커버리지 임계) → `HarnessConfig` | `00_config-harness.json` |
| **0.5** | configure-harness | `detect_spring_profile`로 Boot 2.0–4.x 프로파일 확정. 미감지→질문(CI 중단), 충돌→확정 질문. **가정 금지** | (HarnessConfig에 병합) |
| **0.6** | configure-harness | 빌드 능력 `detect→approve→inject`(JaCoCo XML·PITest 스니펫, `buildChanges[]` 기록) + 콜드 캐시 1회 온라인 프라이밍 결정 | `00b_build_provision.json` |
| **1 ∥ 2** | ingest-specs(spec-reviewer) ∥ analyze-ast(ast-structure-analyzer) | criteria 정규화 ∥ 테스트 대상·의존 그래프 추출 | `01_*.json`, `02_*.json` |
| **3** | analyze-source(source-code-analyzer) | 호출 그래프·외부 I/O(DB/HTTP/clock/random) testSeam·DI/트랜잭션 경계 분석 | `03_*.json` |
| **3.5** | refactor-advisory(refactor-advisor) + full-pipeline 게이트 | 테스트 부적합 코드 판정(§3.3) → `RA-*.md` **항상** 작성 → 포함/제외 결정 → 제외 FQCN을 이후 입력에서 필터 | `03b`, `03c`, `test_docs/refactoring/` |
| **4** | generate-scenarios(scenario-generator) | criteria×seam 매핑으로 최소 시나리오 집합(unit P0 → slice P1 → integration P2), 동치류 3+ → parameterized | `04_scenario_set.json` |
| **4.5** | full-pipeline 승인 게이트 | 시나리오를 `test_docs/scenarios/<id>.md`(approval: pending)로 저장 → 대화형 승인/일부 제외/재설계, CI 자동 승인 → **승인분만** 진행 | `04b_approval.json` |
| **5** | generate-tests(test-code-generator) | 프로파일 분기 코드 생성 — 컨트롤러 `@WebMvcTest`+MockMvc, JPA `@DataJpaTest`, 서비스는 컨텍스트 없는 단위, BDD 3단 본문 | `src/test/java/*`, `05_*.json` |
| **6** | run-tests(test-runner) | 생성 클래스만 대상 한정 실행(Gradle `--tests`/Maven `-Dtest=`), JUnit XML 파싱 | `06_run_result.json` |
| **7** | repair-tests(test-fixer) — 실패 시만 | 실패 유형 분류(COMPILE/RUNTIME/FLAKY/SPEC_MISMATCH/SYMBOL) → 최소 diff 보정 → 6단계 재실행. **그린까지 반복**, 동일 실패 3회 연속(무진전)이면 partial | `07_*.json` |
| **8** | measure-coverage(coverage-closer) | JaCoCo 측정 → `coverage_gate` → 미달 gap에 보완 테스트 생성 → 재측정 루프 | `08_*.json` |
| **9** | mutation-test(mutation-analyst) | PITest → 생존 mutant 단언 강화 → 재실행 루프 (sleep/over-mock/broad-catch 금지) | `09_*.json` |
| **10** | verify-scenarios(scenario-conformance-verifier) | scenarioRef로 시나리오↔테스트 매핑 → satisfied/unsatisfied/missing 판정(then 단언 전수 반영 확인) → `test_docs/` 최종 갱신 | `10_conformance.json` |
| 집계 | full-pipeline | `PipelineResult` JSON + Markdown 보고서 | `pipeline_result.json` |

### 3.3 리팩토링 권고 게이트(3.5)의 판정 기준

[refactor-advisory.md](../references/refactor-advisory.md)(SSOT)의 3범주 — 임의 수치가 아니라 공식/1차 문서 근거로만 플래그한다:

- **complexity**: McCabe 순환복잡도 **CC > 10**(NIST SP 500-235 기준, 11–15 medium / >15 high).
- **testability**: 생성자 실질 작업, `new` 직접 생성·싱글턴 등 숨은 의존, mutable static 상태,
  미주입 `LocalDateTime.now()`/`new Random()` 등 seam, train-wreck 체인, 생성자 인자 >7
  (Spring DI 레퍼런스·Google Testing Guide·Mockito javadoc 근거).
- **efficiency**: 루프 내 repository/EntityManager 조회(N+1), 루프 내 원격 호출·재계산, `FetchType.EAGER` 남용
  (Hibernate User Guide Fetching 장 근거).

플래그돼도 **코드를 고치지 않는다** — 근거·수정법이 담긴 권고 문서(`test_docs/refactoring/RA-*.md`)를 남기고,
"테스트 생성 대상에 포함할지"만 결정한다(제외분도 문서는 보존). 판정 에이전트가 실패하면 경고 후 전 대상
포함으로 진행한다(보조 게이트 — 파이프라인을 막지 않음).

### 3.4 대화형 vs 비대화형(CI) 분기

모든 fallback 지점은 [fallback-policy.md](../references/fallback-policy.md)(19개 정책)의 공통 패턴을 따른다:

- **대화형 CLI**: `AskUserQuestion`으로 묻고 답에 따라 진행/중단. 침묵 degrade·임의 기본값 금지.
- **비대화형(`claude -p`)/CI**: 질문 불가 → **결정적 세팅 항목**(`pip install`, `mvn package`)은 자동 수행 후
  재검증, **비결정적 항목**(버전 미감지·프로파일 충돌·미지정 입력)은 `status:"failed"` + remediation으로
  하드 중단. 승인 게이트(3.5/4.5)는 자동 포함/승인 + 기록. 빌드 파일 자동 주입과 자동 온라인 전환은 **금지**
  (`BUILD_TEST_ALLOW_NETWORK=1` 옵트인).
- CI 모드 감지: `skipInterview: true` · 환경변수 `CI=true`/`CLAUDE_NO_PROMPT=true` · `claude -p` 세션 ·
  인터뷰 4항목이 모두 채워진 HarnessRequest.

### 3.5 부분 재실행

`_workspace/`가 있으면 요청 유형에 따라 영향 단계만 재실행하고 나머지는 기존 JSON을 재사용한다
(정본: [orchestration-detail.md](../skills/full-pipeline/references/orchestration-detail.md) §3):

| 요청 예 | 재실행 | 재사용 |
|---|---|---|
| "이 패키지만 다시" | 2→3→3.5→4→4.5→5→6→8→(9)→10 | `01_spec` |
| "커버리지만 더 올려" | 8→10 | `01~06`, `04b` |
| "뮤테이션만 다시" | 9→10 | `01~08`, `04b` |
| "테스트 실패 고쳐" | 7→6→10 | `01~05`, `04b` |
| "시나리오 만족하는지만 확인" | 10 | `01~09`, `04b` |

새 입력으로 완전히 다시 돌리면 기존 `_workspace/`는 `_workspace_{timestamp}/`로 옮겨 보존한다.

---

## 4. 설치

### 4.1 마켓플레이스 설치 (권장)

이 저장소 자체가 Claude Code 마켓플레이스다(`.claude-plugin/marketplace.json`). Claude Code 세션에서:

```text
/plugin marketplace add 1223v/test-autoevermation-harness
/plugin install test-autoevermation-harness-plugin@test-autoevermation-harness
```

업데이트는 저장소에 push된 뒤 `/plugin marketplace update`로 갱신한다(플러그인 `version`이 올라갈 때
사용자에게 전달됨). 수동 설치를 원하면 `test-autoevermation-harness-plugin/`을 `~/.claude/plugins/` 아래에
복사(또는 symlink)하고 Claude Code를 재시작해도 된다.

설치 확인: 세션에서 `/test-autoevermation-harness-plugin:full-pipeline` 명령이 자동완성에 뜨면 정상.

### 4.2 MCP 런타임 (자동)

MCP 서버 3종은 Python으로 돈다. **v0.12.0부터 의존성은 자동 설치된다** — 첫 세션에서
`mcp/bootstrap.py`가 `${CLAUDE_PLUGIN_DATA}/venv`(플러그인 업데이트에도 유지)에
`mcp[cli]`를 1회 설치하고, `.mcp.json`과 SessionStart 훅이 이를 사용한다.
**Python 자체도 없어도 된다**(v0.13.0+, macOS/Linux/WSL) — PATH에 3.10+가 없으면 `mcp/run-server.sh`가
uv(무-sudo, `~/.local`)로 관리형 Python을 자동 설치한다(`HARNESS_AUTO_PYTHON=0`으로 비활성화).
**Windows 네이티브는 미지원** — MCP 진입점이 POSIX `sh` 기반이고 Git for Windows도 선택 설치라
`sh` 보장이 없다(공식 setup 문서). Windows에서는 WSL로 사용한다. 자동 설치가 실패한
환경(오프라인 등)의 수동 폴백:

```bash
python3 -m pip install -r mcp/requirements.txt    # mcp[cli]>=1.2.0, Python 3.10+
```

### 4.3 JavaParser AST 백엔드 (권장, 선택)

정밀 AST를 원하면 jar를 빌드한다(JDK 17+, Maven 3.6.3+). 없으면 정규식 fallback으로
degrade(`degraded:true` 경고)하며 파이프라인은 계속 동작한다.

```bash
cd mcp/javaparser-cli && mvn -q -DskipTests package     # → target/astcli-1.0.0-shaded.jar
# 다른 위치의 jar를 쓰려면: export REPO_AST_JAVAPARSER_JAR=/abs/path/astcli-1.0.0-shaded.jar
# 정규식 fallback 없이 하드실패를 원하면(opt-in): export REPO_AST_REQUIRE_JAVAPARSER=1
```

### 4.4 JDT LS (선택)

semantic 분석 보강용. `jdtls`가 PATH에 있고 Java 21+ 런타임이 있으면 `.lsp.json`으로 자동 연결되고,
없으면 AST-only로 진행한다(차단 없음).

> 위 4.2~4.4는 수동 명령이지만, 실제로는 **Phase E가 시작 시 감지해서 대화형이면 "지금 함께
> 세팅할까요?"로 묻고, CI면 결정적 항목(pip/mvn)을 자동 수행**한다 — 보통 손으로 미리 할 필요가 없다.

---

## 5. 사용법

### 5.1 빠른 시작 (대화형)

Spring 프로젝트를 연 Claude Code 세션에서:

```text
/test-autoevermation-harness-plugin:full-pipeline
```

이후 하네스가 묻는 것들(전형적 순서):

1. **Phase E**: 미충족 환경 항목별 "지금 함께 세팅할까요?" (MCP SDK 설치, jar 빌드 등)
2. **0.5**: Boot 버전을 감지 못했거나 충돌하면 메이저 버전/우선 기준 선택
3. **0.6**: JaCoCo XML·PITest가 빌드 파일에 없으면 "최소 스니펫을 주입할까요?", 콜드 캐시면 "1회 온라인 프라이밍?"
4. **인터뷰 4항목**: 스펙 문서 경로 / 테스트 대상(패키지·FQCN·모듈, 또는 자동 탐지) / 뮤테이션 깊이 / 커버리지 임계값·제외
5. **3.5 게이트**: 리팩토링 권고가 있으면 "전체 포함(권장) / 일부 제외 / 전체 제외"
6. **4.5 게이트**: 시나리오 "전체 승인 / 일부 제외·수정 / 재설계 요청"
7. 완료 후 **Markdown 보고서** + `test_docs/` + 생성 테스트 확인

"스프링 테스트 생성해줘", "커버리지 더 올려", "뮤테이션만 다시" 같은 자연어도 스킬 트리거로 인식된다
(각 SKILL.md의 자동 호출 조건).

### 5.2 개별 스킬만 쓰기

전체 파이프라인 없이 단계 하나만 돌릴 수 있다. 예:

```text
/test-autoevermation-harness-plugin:analyze-ast          # 테스트 대상·구조만 추출
/test-autoevermation-harness-plugin:refactor-advisory    # 테스트 부적합 코드 판정만 (read-only)
/test-autoevermation-harness-plugin:measure-coverage     # 기존 테스트로 커버리지 게이트만
/test-autoevermation-harness-plugin:verify-scenarios     # 시나리오 충족 여부만 재검증
```

### 5.3 비대화형 / CI

`claude -p`로 호출하면 인터뷰·게이트가 자동 정책으로 대체된다(§3.4). **미지정 필수 입력은 하드 중단**되므로
`HarnessRequest`를 채워서 호출한다:

```bash
claude -p --output-format json "/test-autoevermation-harness-plugin:full-pipeline {
  \"projectRoot\": \"$PWD\",
  \"specDocPaths\": [\"docs/api-spec.md\"],
  \"targets\": [\"com.example.order\"],
  \"buildTool\": \"gradle\",
  \"javaVersion\": \"17\",
  \"springVersion\": \"3.4.0\"
}"
```

CI 주의사항:

- 빌드 파일 자동 주입 금지 → JaCoCo XML·PITest 설정을 **미리** 빌드 파일에 반영해 두거나, 감지 실패 시
  remediation(제안 스니펫 포함)으로 중단된다.
- 기본 오프라인 → 캐시가 비어 있으면 사전 워밍업(예: `mvn dependency:go-offline`)을 해 두거나
  `BUILD_TEST_ALLOW_NETWORK=1`을 옵트인한다.
- GitHub Actions 예제: [examples/ci/gradle-ci.yml](../examples/ci/gradle-ci.yml) · [maven-ci.yml](../examples/ci/maven-ci.yml)

### 5.4 이어서 작업하기 (부분 재실행)

같은 프로젝트에서 다시 부르면 `_workspace/`를 감지해 필요한 단계만 돈다: "이 패키지만 다시",
"임계값 바꿔서 다시", "테스트 실패 고쳐" 등(§3.5 표). 도메인 특화 설정을 재사용하려면
configure-harness 마지막의 **도메인 스킬 스캐폴딩**으로 `/test-autoevermation-harness-plugin:<custom>` 스킬을 만들어 둘 수 있다.

### 5.5 상태줄 진행률 표시 (선택)

`/test-autoevermation-harness-plugin:setup-statusline`을 실행하면 Claude Code 상태줄에 플러그인 버전과
full-pipeline 진행률이 한 줄 추가된다(기존 상태줄 출력은 그대로 유지):

```text
[Test-AutoEverMation#0.11.0]                                    ← 파이프라인 없음(버전만)
[Test-AutoEverMation#0.11.0] 43% | stage 4: generate-scenarios  ← 진행 중(_workspace/ 산출물 기반)
[Test-AutoEverMation#0.11.0] 100% | done (ok)                   ← 완료(pipeline_result.json의 status)
```

동작 원리: 스킬이 `~/.claude/settings.json`의 `statusLine` 커맨드를 래퍼(`scripts/test-autoevermation-statusline.py`)로
교체하고, 기존 커맨드는 `~/.claude/test-autoevermation-statusline.json`에 delegate로 보존해 래퍼가 계속 실행한다.
진행률은 프로젝트 루트 `_workspace/`의 단계 산출물(§3.2) 존재 여부로 계산한다 — 읽기 전용, 파이프라인 비침습.
제거는 같은 스킬에 "제거"라고 요청하면 원래 statusLine으로 복원된다.

주의: 플러그인 업데이트 후나 다른 도구가 statusLine을 덮어쓴 경우 스킬을 재실행하면 복구된다.
상세: [skills/setup-statusline/SKILL.md](../skills/setup-statusline/SKILL.md).

---

## 6. 설정

### 6.1 HarnessRequest (파이프라인 입력)

| 필드 | 기본값 | 설명 |
|---|---|---|
| `projectRoot` | 미지정 → 질문/중단 | 대상 프로젝트 루트 |
| `specDocPaths` | `[]` | 스펙 문서 경로 목록 |
| `targets` / `targetModules` | `[]` | 대상 패키지·FQCN / 멀티모듈 대상 |
| `buildTool` | 미지정 → 감지+확정 | `gradle` \| `maven` |
| `junitPolicy` | `jupiter-style` | `jupiter-style`(BOM 위임) \| `strict-5x`(version pin+경고) |
| `testScope` | `mixed` | `unit`/`slice`/`integration`/`mixed` |
| `javaVersion` / `springVersion` | 미지정 → 감지+확정 | 프로파일 결정 입력 |
| `stylePolicy` | `google-java` | 코드 스타일 |
| `lspAvailable` | E7 감지값 | JDT LS 보강 경로 활성화 |
| `maxRepairRetries` | `2` | 보정 루프 진전 추적 단위(상한 아님) |
| `domainKeywords` | `[]` | 스펙 검색 힌트 |
| `refactorAdvisory` | `{enabled: true}` | 3.5단계 제어. `thresholds{cyclomatic:10, constructorArgs:7}` 오버라이드 가능 |

미지정 필드는 **자동 기본값으로 채우지 않는다**(fallback-policy #13) — 대화형은 질문, CI는 중단.

### 6.2 HarnessConfig (0단계 산출)

인터뷰 + HarnessRequest + 감지 결과가 병합된 실행 설정. 핵심 블록:

- `springProfile{bootVersion, namespace, junitEngine, mockAnnotation, mockImport, javaBaseline, …}` — 0.5단계 확정
- `coverage{line:0.95, branch:0.90, method:0.95, class:1.00, excludes[...]}` — 기본 제외:
  `**/*Application*`, `**/config/**`, `**/dto/**`, `**/generated/**`
- `mutation{mutators:"DEFAULTS", mutationThreshold:0.80, targetClasses, targetTests, threads}`
- `coverageMaxIterations`/`mutationMaxIterations`(기본 3 — 진전 추적 단위)
- `refactorAdvisory{enabled, thresholds}` (인터뷰 항목 아님 — HarnessRequest로만 오버라이드)

전체 스키마 정본: [configure-harness/SKILL.md](../skills/configure-harness/SKILL.md) 「5단계」.

### 6.3 환경변수 (.mcp.json / opt-in)

| 변수 | 기본 | 의미 |
|---|---|---|
| `REPO_AST_ALLOW_ROOT` | `${CLAUDE_PROJECT_DIR}` | repo-ast 경로 allowlist 루트(밖은 거부) |
| `REPO_AST_JAVAPARSER_JAR` | 자동 탐색 | JavaParser CLI jar 경로 지정 |
| `REPO_AST_REQUIRE_JAVAPARSER` | 미설정 | `1`이면 jar 없을 때 정규식 fallback 대신 하드실패 |
| `SPEC_DOC_ALLOWLIST` | `docs,specs,requirements` | spec-doc이 읽을 수 있는 하위 디렉터리 |
| `SPEC_DOC_REDACT` | `on` | 민감정보 마스킹 |
| `SPEC_DOC_WORKSPACE` | `${CLAUDE_PROJECT_DIR}` | spec-doc 경로 봉쇄 루트 |
| `BUILD_TEST_ALLOW_NETWORK` | `0` | 테스트 실행 네트워크(옵트인, CI 프라이밍용) |

---

## 7. 산출물

파이프라인이 끝나면 **대상 프로젝트**에 세 종류가 남는다:

```
<projectRoot>/
├── src/test/java/**            ← 생성된 테스트 (커밋 대상)
├── test_docs/                  ← living documentation (커밋 가능)
│   ├── INDEX.md                  시나리오↔테스트코드↔결과 매핑표 + 리팩토링 권고 요약
│   ├── scenarios/SC-*.md         시나리오 1건 1파일 (BDD + 승인 상태 + 매핑 + 검증 결과)
│   └── refactoring/RA-*.md       리팩토링 권고 (근거·수정법·포함/제외 결정)
└── _workspace/                 ← 중간 JSON·timing (감사/부분 재실행용, .gitignore 권장)
```

생성 테스트의 컨벤션:

- 클래스: `<Target>Test`(단위/슬라이스), `<Target>IT`(통합). 대상과 동일 패키지의 `src/test/java`.
- 메서드: `<scenarioRefSlug>_<행위>` (예: `sc001_재고부족이면_주문생성이_실패한다`) + javadoc에
  `scenarioRef`/`criteriaRef` — 10단계 적합성 검증이 이 링크로 매핑한다.
- 본문: `// given` → `// when`(단일 행위) → `// then` 3단, stub은 BDDMockito `given().willReturn()`,
  Jupiter 프로파일은 `@DisplayName` 한국어 행위 서술.
- 상태 판정: 시나리오 전부 satisfied → `status: ok`, unmet 존재/무진전 중단 → `partial`(잔여 전량 보고),
  환경/전제 실패 → `failed`(remediation 포함). **임의 제외·침묵 누락 없음.**

---

## 8. 보안 모델

| 항목 | 구현 |
|---|---|
| 네트워크 기본 차단 | `BUILD_TEST_ALLOW_NETWORK=0` + `guard-network.py` 훅. 유일한 예외는 사용자가 승인한 1회 캐시 프라이밍(`online=True`) |
| 경로 allowlist | repo-ast `REPO_AST_ALLOW_ROOT`, spec-doc `SPEC_DOC_ALLOWLIST`+`SPEC_DOC_WORKSPACE` — 프로젝트 밖·vendor/build/generated read 거부 |
| 소스 노출 최소화 | repo-ast는 메서드 본문 미반환(구조 메타만), 에이전트 결과에 소스 원문 금지 |
| 민감정보 | `redact-secrets.py` 훅 + spec-doc redaction (토큰·이메일·접속문자열) |
| 쉘 안전 | `run_targeted_tests`가 shlex로 인자 escaping 강제 |
| 에이전트 권한 | frontmatter `tools:` 최소 권한(§2.3) — read-only 판정 에이전트는 Write/Bash 불가 |

---

## 9. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| MCP 서버 3종이 연결 안 됨 | (자동 설치 실패 — 오프라인/curl·wget 없음/Windows 네이티브/`HARNESS_AUTO_PYTHON=0`) | **세션 시작 화면에 표시된 수동 폴백 명령**(v0.13.1+, SessionStart 훅 exit 2 안내)을 따른다: Python 3.10+ 설치 → `python3 -m pip install -r mcp/requirements.txt` → `/reload-plugins`. 상세 진단은 `mcp-logs-plugin-*` 로그의 `run-server`/`bootstrap` 줄 |
| `degraded:true` + 정규식 fallback 경고 | JavaParser jar 미빌드/JDK 없음 | §4.3으로 jar 빌드 또는 `REPO_AST_JAVAPARSER_JAR` 지정. 하드실패 원하면 `REPO_AST_REQUIRE_JAVAPARSER=1` |
| 커버리지(8)/뮤테이션(9)이 리포트를 못 찾음 | Gradle JaCoCo **XML 기본 OFF**·PITest 플러그인 부재 | 0.6단계 주입 승인, 또는 [build-provisioning.md](../references/build-provisioning.md) §1 스니펫을 빌드 파일에 직접 반영 |
| 첫 실행(6)에서 의존성 해석 실패 | 콜드 캐시 + 기본 오프라인 | 1회 온라인 프라이밍 승인 / CI는 사전 `dependency:go-offline` 또는 `BUILD_TEST_ALLOW_NETWORK=1` |
| Mockito mock 생성 실패 (JDK 24/25) | inline mock-maker ↔ 신형 JDK 비호환 | 실행 JDK를 17/21 LTS로, 또는 Mockito 5.16+(ByteBuddy 1.17+), 또는 `-Dnet.bytebuddy.experimental=true` (E10) |
| `BUILD_TOOL_UNDETECTED` | wrapper/빌드파일 미감지 | 대화형은 질문에 답, CI는 `HarnessRequest.buildTool` 명시 |
| `INTERVIEW_REQUIRED`/`PROFILE_CONFLICT`로 중단(CI) | Boot 버전 미감지·빌드파일↔소스 불일치 | `HarnessRequest.springVersion` 명시(가정 생성 방지를 위한 의도된 중단) |
| `@MockBean`/`@MockitoBean` 컴파일 에러 | 프로파일 오버라이드로 버전과 불일치 | 0.5단계 감지값 확인 — Boot ≤3.3은 `@MockBean`, 3.4+는 `@MockitoBean`([version-compatibility.md](../references/version-compatibility.md)) |
| `status: partial`로 종료 | unmet 시나리오/무진전 3회/전량 제외 등 | 보고서의 잔여 목록·사유 확인 → "테스트 실패 고쳐"/"커버리지만 더 올려" 등으로 부분 재실행 |
| JDT LS 에러 탭 표시 | `jdtls` 미설치/Java 21 미만 | 선택 기능 — 무시해도 AST-only로 정상 동작. 원하면 jdtls + Java 21+ 설치 |

---

## 10. 문서 지도

| 문서 | 역할 |
|---|---|
| [README.md](../README.md) | 요약 소개·설치·표 위주 레퍼런스 |
| **GUIDE.md (이 문서)** | 동작 원리·사용법 종합 가이드 |
| [docs/pipeline-flow.md](./pipeline-flow.md) | 전체 흐름 Mermaid 다이어그램 |
| [skills/full-pipeline/SKILL.md](../skills/full-pipeline/SKILL.md) | 오케스트레이션 정본(단계별 Task 호출·실패표) |
| [skills/full-pipeline/references/orchestration-detail.md](../skills/full-pipeline/references/orchestration-detail.md) | `_workspace/` 규약·부분 재실행 매트릭스·timing |
| [references/environment-setup.md](../references/environment-setup.md) | Phase E 체크리스트(E1~E12) SSOT |
| [references/fallback-policy.md](../references/fallback-policy.md) | fallback 19개 정책 SSOT |
| [references/scenario-docs.md](../references/scenario-docs.md) | `test_docs/`·승인·적합성 검증 SSOT |
| [references/refactor-advisory.md](../references/refactor-advisory.md) | 3.5단계 판정 기준·임계값 SSOT |
| [references/build-provisioning.md](../references/build-provisioning.md) | JaCoCo XML·PITest 주입·캐시 프라이밍 SSOT |
| [references/version-compatibility.md](../references/version-compatibility.md) | Boot 2.0–4.x 프로파일별 전체 코드 템플릿 |
| [references/custom-components.md](../references/custom-components.md) | 커스텀 스테레오타입 인식 규칙 |
| [RESEARCH_NOTES.md](../RESEARCH_NOTES.md) | 핀 고정 버전·API·공식문서 근거(런타임 SSOT) |
| [DEPENDENCIES.md](../DEPENDENCIES.md) | OMC 비의존 선언·런타임 의존성 표 |
| [CHANGELOG.md](../CHANGELOG.md) | 버전별 변경 이력 |
| [examples/](../examples/) | 프로파일별 테스트/빌드/CI 예제 13종 |
