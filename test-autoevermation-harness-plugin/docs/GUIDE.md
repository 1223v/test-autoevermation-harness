# Spring 테스트 하네스 — 동작 원리·사용 가이드 (GUIDE)

> Codex 앱·CLI 설치와 실행은 [CODEX.md](CODEX.md), 호스트별 실행 차이는 [host-runtime.md](../references/host-runtime.md)를 따른다. 이 가이드의 Claude 도구·LSP·상태줄·훅 예시는 Claude 전용이며 공용 단계·검증·산출물은 두 호스트에서 유지한다.

이 문서는 `test-autoevermation-harness-plugin` 플러그인이 **어떤 구조로, 어떤 순서로 동작하는지**와
**설치부터 실행·설정·산출물 해석까지 어떻게 사용하는지**를 한 곳에 정리한 종합 가이드다.

- 공용 구조·사용 흐름: [ARCHITECTURE.md](ARCHITECTURE.md)
- 호환성 수정·검증: [compatibility-remediation.md](compatibility-remediation.md)
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

**Spring 프로젝트에 테스트 코드를 생성·검증하는 Codex 앱·CLI 및 Claude Code 공용 플러그인**이다. 아래 슬래시 명령과 Agent/LSP/훅은 Claude 예시이고 Codex는 CODEX.md의 자연어 요청·호스트 지침을 사용한다.
명령 하나(`/test-autoevermation-harness-plugin:full-pipeline`)로 아래 전 과정을 오케스트레이션한다.

```
스펙 문서 인덱싱 ─┐
                  ├→ 소스 분석 → 리팩토링 권고 게이트 → 시나리오 설계 → 사용자 승인
AST 구조 추출  ───┘                                                        │
                                                                           ▼
   시나리오 적합성 검증 ← 커버리지 게이트 ← 실패 보정 ← 실행 ← 테스트 생성
```

핵심 특성:

- **버전 인식(Boot 2.0–4.x)**: 대상 프로젝트의 Spring Boot 버전 프로파일을 감지해
  `javax`/`jakarta` 네임스페이스, JUnit4/Jupiter 엔진, `@MockBean`/`@MockitoBean`을 자동 분기한다.
  컴파일되는 테스트를 만들기 위한 전제이며, 매트릭스 정본은 [RESEARCH_NOTES §8](../RESEARCH_NOTES.md).
- **BDD living documentation**: 시나리오는 given/when/then 구조로 설계되고, 테스트 메서드명에
  `scenarioRef`(`SC-001` → `sc001_…`)가 박히며, 결과가 대상 프로젝트의 `test_docs/`에
  시나리오↔테스트코드↔결과 매핑으로 영속화된다.
- **승인과 검증**: 리팩토링 권고는 시나리오 승인에서 함께 제시한다. 승인한 시나리오만 생성하고 실제 테스트·JaCoCo·적합성을 확인한다.
- **보정 예산**: 빠름 1회·균형 3회는 원인을 합산하며 엄격/기존은 무진전 종료 규칙을 유지한다. 마지막 수정 뒤 검증도 생략하지 않는다.
- **독립 실행**: oh-my-claudecode 등 외부 플러그인에 의존하지 않는다. Claude Code 네이티브 기능
  (플러그인·질문·MCP·훅)을 사용하며 위임은 선택이다 — Python 3.10+는 없으면
  자동 설치된다(v0.15.0+, 전 OS: macOS/Linux/WSL/Windows). 상세: [DEPENDENCIES.md](../DEPENDENCIES.md).

---

## 2. 아키텍처

### 2.1 구성요소 한눈에

```
test-autoevermation-harness-plugin/
├── .claude-plugin/plugin.json   ← 매니페스트: skills/·.mcp.json·.lsp.json 등록(표준 hooks/hooks.json은 자동 로드)
├── skills/        (15종)        ← /test-autoevermation-harness-plugin:<name> 명령. 절차(무엇을 어떤 순서로)의 정의
├── agents/        (11종)        ← Agent(subagent_type=...)로 호출되는 서브에이전트. 실제 분석/생성 수행
├── mcp/           (서버 3종)    ← Python MCPServer stdio 서버. 결정적 작업(파싱·빌드실행·리포트 해석)
│   └── javaparser-cli/          ← JavaParser 기반 정밀 AST CLI (mvnw 동봉, 필수 빌드)
├── hooks/hooks.json + scripts/  ← 산출물·승인 게이트(PreToolUse deny)·실행 증거 기록·시크릿 warn 보고
├── references/    (9종)         ← 정책·절차의 SSOT 문서 (스킬·에이전트가 인용)
├── docs/                        ← 이 가이드 + pipeline-flow.md(다이어그램)
└── .lsp.json                    ← (필수) Eclipse JDT LS 등록
```

역할 분담 원칙: **스킬 = 절차서**(단계·게이트·fallback 분기를 기술), **에이전트 = 실행자**(권한이
최소화된 read-only/write 분리), **MCP 서버 = 결정적 도구**(같은 입력이면 같은 출력 — 빌드 실행,
XML 파싱, 버전 감지 등 LLM에 맡기면 안 되는 부분).

### 2.2 Skills (15종)

| Skill | 파이프라인 단계 | 역할 |
|---|---|---|
| **`setup-harness`** | **사전(선행)** | **환경 세팅 전용 — E1~E10(Python·MCP 런타임·MCP 라이브 연결·JDK 21+·JavaParser jar·JDT LS) + 상태줄 설치.** 플러그인 설치 후 최초 1회 실행, 멱등 재실행 가능 |
| `configure-harness` | E-verify + 0/0.5/0.6 | **세팅 검증 게이트(E-verify)** → Spring 프로파일 감지 → 3항목 인터뷰 → `HarnessConfig` 생성 (**환경을 세팅하지 않는다**) |
| `full-pipeline` | 전체 | end-to-end 오케스트레이션(아래 §3) |
| `ingest-specs` | 1 | 스펙 문서 인덱싱·acceptance criteria(Given/When/Then) 정규화 |
| `analyze-ast` | 2 | JavaParser 기반 AST 구조·테스트 대상 추출 |
| `analyze-source` | 3 | 동작·외부 I/O·mocking seam 분석 |
| `refactor-advisory` | 3.5 (판정부) | 복잡도·비효율·테스트 저해 코드 판정 (read-only) |
| `generate-scenarios` | 4 | unit/slice/integration 시나리오 설계 (BDD) |
| `generate-tests` | 5 | JUnit + Spring Test 코드 생성 (버전 프로파일 분기) |
| `run-tests` | 6 | 빌드 도구 감지 후 최소 범위 테스트 실행 |
| `repair-tests` | 7 | 실패 원인 분류 후 최소 diff 보정 |
| `measure-coverage` | 8 | JaCoCo 측정·결과 공유, 개선은 요청 시만 |
| `verify-scenarios` | 9 | 시나리오 적합성 검증 + `test_docs/` 정리 |
| `setup-statusline` | (부가) | Claude Code statusLine에 Test-AutoEverMation 진행률 줄(버전·%·현재 단계) 설치/제거 (`setup-harness` S1과 동일 스크립트) |
| `edit-tests` | 파이프라인 외 (사후) | 사용자가 지목한 기존 테스트를 repo-ast AST 근거로 직접 편집(이름 변경·단언 추가/조정·정리). 실행은 `run-tests`로 안내 |

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
| `scenario-conformance-verifier` | 9단계 | Read/Write/Edit/Grep/Glob + MCP — 테스트 생성/수정 금지(문서화 전용) |
| `test-editor` | 파이프라인 외 (사후) | Read/Write/Edit/Grep/Glob + MCP(repo-ast) — Bash 없음(편집만, 실행 안 함) |

권한은 각 `agents/*.md`의 frontmatter `tools:` 목록으로 강제된다. 플러그인 배포 에이전트는
`hooks`/`mcpServers`/`permissionMode` frontmatter를 선언할 수 없다는 것이 Claude Code 공식 제약이라
([Plugins reference](https://code.claude.com/docs/en/plugins-reference)), MCP 접근은 공유 `.mcp.json` +
스킬 라우팅으로 구현한다. 모든 에이전트는 `model: inherit`라 세션 모델 그대로 동작한다(특정 티어 불필요).

### 2.4 MCP 서버 3종 (Python MCPServer, stdio)

공식 MCP Python SDK의 `MCPServer` 고수준 API(`@mcp.tool()` 데코레이터, `mcp.run(transport="stdio")`)로
구현되어 있고, `.mcp.json`이 `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs ${CLAUDE_PLUGIN_ROOT}/mcp/<server>.py`로 기동한다(v0.15.0+ — launch.cjs가 Python 런타임·의존성을 자동 프로비저닝, §4.2).
`${CLAUDE_PLUGIN_ROOT}`(플러그인 설치 경로)·`${CLAUDE_PROJECT_DIR}`(현재 프로젝트 루트)는 Claude Code가
치환·주입하는 공식 변수다.

| 서버 | 도구 | 설명 |
|---|---|---|
| `repo-ast` | `parse_java_file` · `resolve_symbol` · `list_spring_components` · `extract_test_targets` · `health` | 구조 전용 Java AST/심볼 분석. **메서드 본문은 절대 반환하지 않음**(시그니처·애노테이션·메타만). JavaParser jar(`mcp/javaparser-cli`, v0.16.0부터 **필수**, 유일한 백엔드) — 미가용 시 하드실패(`JAVAPARSER_REQUIRED`). 일부 파일만 파싱 실패하면 그 파일을 제외하고 `degraded:true`+`warnings`에 파일명 명시. `health`가 jar/JDK 상태를 반환. 커스텀 스테레오타입(`@Component` 메타 애노테이션)을 전이적으로 해석 |
| `spec-doc` | `index_docs` · `search_requirements` · `extract_acceptance_criteria` · `health` | 스펙 문서 청크 인덱싱·요구사항 검색·Given/When/Then criteria 추출. 경로 allowlist(`SPEC_DOC_ALLOWLIST`) + 민감정보 redaction |
| `build-test` | `detect_build_tool` · `detect_spring_profile` · `detect_build_capabilities` · `check_dependency_cache` · `list_test_tasks` · `run_targeted_tests` · `parse_junit_xml` · `parse_jacoco_report` · `coverage_gate` · `detect_pipeline_state` · `health` | Gradle/Maven 감지, Boot 프로파일 감지, 필수 JaCoCo XML 능력 감지, 캐시 신호, 대상 한정 테스트 실행, 리포트 파싱, 커버리지 게이트, 영속 증거 기반 상태 복원 |

`setup-harness`의 `E3b`가 `health` 3종을 실호출해 세션에 실제로 연결됐는지 세팅·검증하고, 파이프라인 시작 전 E-verify 프로브가 이를 재확인한다
(실패 시 하드 중단 — [environment-setup.md](../references/environment-setup.md)).

세 서버 모두 **MCP tool만 노출한다 — 리소스·프롬프트는 없다.** v0.33.0에서 리소스 4종(`ast://index`,
`ast://dependency-graph`, `spec://glossary`, `spec://requirement-matrix`)과 프롬프트 3종
(`explain_target_shape`, `review_specs_for_testing`, `suggest_test_command`)을 삭제했다. MCPServer 보일러플레이트
([RESEARCH_NOTES.md](../RESEARCH_NOTES.md) §1)에서 그대로 옮겨진 것들로, 에이전트 11개 전원의 도구 목록에
`ReadMcpResourceTool`이 없어 파이프라인이 호출할 수 없었고 전부 살아 있는 tool·에이전트의 열등한 중복이었다.
게다가 `ast://` 2종은 tool과 달리 `paths` 인자가 없어 매 읽기마다 allow root 전체를 `_analyze()`했고,
프롬프트 2종은 실제 계약에서 드리프트해 틀린 안내(무조건 `--offline`, Boot ≤3.3에 `@MockitoBean`)를 했다.
**MCP 서버는 stdio라 사용자에게 질문할 수 없다** — 조건을 신호(`degraded`/`requiresConfirmation`/error code)로
노출만 하고, 질문/중단 판단은 스킬·에이전트 계층이 한다([fallback-policy.md](../references/fallback-policy.md) 공통규칙 3).

### 2.5 Hooks + LSP

| 훅 | 시점 | 동작 |
|---|---|---|
| `scripts/record-run-context.py` | PreToolUse(Skill·Agent — 구 Task alias 포함) + PostToolUse(detect_pipeline_state) | **v0.22.0 실행 강제(enforcement) 기록자**: full-pipeline 호출 시 cwd와 대상 `projectRoot`의 `_workspace/.markers/run.json`(하네스 활성·라우팅) 기록 + 단계 계약 리마인더 주입, 파이프라인 subagent 스폰 시 대상 프로젝트에 `spawn-<agent>.json` 기록(위임 증거), `detect_pipeline_state`의 실제 요청 root·커버리지 임계값과 응답을 결합해 durable-resume allowlist를 기록. 시나리오 미승인(`04b` 부재) 상태의 test-code-generator 스폰은 deny |
| `scripts/guard-gate-artifacts.py` | PreToolUse(Write·Edit) | **산출물 검사**: 승인·공유 예산·테스트 파일 역할·순서 게이트와 8단계 커버리지 불변식을 검사한다. **파이프라인이 도는 세션에서만 판정**(아래) |
| `scripts/redact-secrets.py` | PostToolUse(Write·Edit) | 생성물의 토큰·비밀번호·접속문자열 패턴을 **보고**(warn 모드 — 파일을 수정하지 않으며, 발견 내용은 `hookSpecificOutput.additionalContext`로 모델에 전달) |

**쓰기 가드의 단일 게이트(v0.32.0).** `guard-gate-artifacts.py`는 이제
`_workspace/.markers/run.json`의 `session_id`가 현재 세션과 일치할 때 — 즉 **full-pipeline이 실제로
도는 동안에만** 판정한다. 그 외에는 경로·내용과 무관하게 전부 allow다.

이 한 줄이 이 훅의 역사 전체를 설명한다. v0.22.0 도입 시 Zone B/C에는 run-active 게이트가 있었지만
**markers 검사와 Zone A에는 없었다.** 그래서 하네스를 쓰지 않는 세션에서도 `_workspace/` 경로만
건드리면 차단됐고, 그 오탐 때문에 v0.30.0에서 훅을 등록 해제하고 v0.31.0에서 파일까지 삭제했다.
결과적으로 `fallback-policy.md #21`(커버리지 게이트 무효 조건)과 단계 순서 계약이 기계 검증을 잃었다.
v0.32.0은 **빠져 있던 게이트를 전 Zone에 적용**해 강제를 되살렸다 — 문제는 "쓰기를 막는 것"이 아니라
"파이프라인 밖에서도 막는 것"이었기 때문이다.

회귀 방지: `test_non_pipeline_session_is_never_blocked`(6개 경로가 파이프라인 밖에서 전부 통과),
`test_same_paths_are_guarded_once_the_run_is_active`(같은 경로가 실행 중엔 차단),
`test_write_guard_judges_nothing_outside_an_active_run`(전 Zone이 게이트 뒤에 있는지 구조 검사).

> 도구 제약 가능 경로(훅·에이전트 frontmatter·MCP 환경변수·`settings.json`)의 **전수 감사**는
> [tool-restrictions.md](./tool-restrictions.md)에 등급별로 정리했다. "하네스 때문에 뭐가 막히나?"는
> 그 문서 하나로 답한다.

**보안 훅 2종 제거(v0.29.0).** `guard-read.py`(Read·WebFetch)와 `guard-network.py`(Bash)는 삭제했다.
근거: ① 보호 대상인 서브에이전트의 권한 경계는 이미 각 `agents/*.md`의 `tools:` 목록이 결정하고
(에이전트 11종 중 `WebFetch`/`WebSearch` 보유 0개, `Bash` 보유는 `test-runner`·`test-fixer` 2종뿐),
② guard-read는 세션 상태를 보지 않아 **하네스와 무관한 세션의 WebFetch·`build/`·`target/` Read까지
차단**하면서 모든 Read 호출마다 node+python 기동 비용(실측 ~54ms)을 물렸으며,
③ 실제로 중요한 "테스트 실행이 네트워크를 타지 않는 것"은 훅이 아니라 **build-test MCP 서버**가
독립적으로 강제한다(`BUILD_TEST_ALLOW_NETWORK`, `.mcp.json` 기본값 `0` → gradle `--offline`/maven `-o`).
증거 기록 훅(`record-run-context.py`)은 오케스트레이션 할루시네이션을 막는 물리 장치이므로
그대로 유지한다. 이 훅의 유일한 deny는 `Task|Agent` 매처의 4.5 승인 게이트(시나리오 미승인
상태의 `test-code-generator` 스폰)이며, **하네스 파이프라인이 활성인 세션에서만** 발동한다 —
쓰기 도구와 무관하므로 v0.30.0 차단 해제 대상이 아니다.

**`_workspace/.markers/` 컨벤션(v0.22.0).** 훅 간 공유되는 물리 증거 저장소: `run.json`(세션별 하네스 활성 신호와 정규화된 `projectRoot`), `spawn-<subagent_type>.json`(대상 프로젝트의 선택 위임의 관측 기록), `pipeline-state.detected.json`(실제 탐지 요청·응답에 결합된 durable-resume 허용 목록). full-pipeline을 호출할 때마다 같은 Claude 세션이어도 이전 spawn/detect 증거는 자동 청소된다. 08 복원 권한은 호출 임계값 4종이 유효한 schema v2 config와 같을 때만 부여하며, config가 없으면 네 값 모두 1.0이어야 한다. **v0.29.0부터 `detect_pipeline_state`가 stale로 판정한 증거(소스가 리포트보다 새로움)에는 복원 권한을 부여하지 않는다.** 이 디렉터리는 훅 전용이라 Write/Edit로 수정할 수 없다. 인프라 오류 시 훅은 fail-open(세션 불파괴), 판정 로직은 fail-closed다. 계약 드리프트 재검용 프로브는 `scripts/dev/probe-hook-stdin.py`.

`settings.json`은 **권장 권한값 문서**다 — Claude Code는 플러그인 settings.json의 `permissions`를
자동 적용하지 않으므로(공식 제약), 이 자세를 원하는 사용자가 자기 프로젝트 `.claude/settings.json`
또는 `~/.claude/settings.json`에 복사해 쓴다. v0.29.0부터 플러그인은 이를 훅으로 대신 강제하지 않는다.

`.lsp.json`은 Eclipse JDT LS(`jdtls`)를 등록한다(Java 21+ 런타임 필요, v0.16.0부터 **필수**). `command`는
node 래퍼 `mcp/jdtls-launcher.cjs`를 거쳐 PATH → 프로비저닝 경로 순으로 `jdtls` 실행 파일을 찾는다.
미설치 시 `scripts/setup_jdtls.py`가 PATH → brew(macOS) → eclipse.org milestone tarball
(`${CLAUDE_PLUGIN_DATA}/jdtls`) 순으로 자동 설치를 시도하며, 그래도 실패하면 (`setup-harness`·E7) 하드 중단한다 —
AST-only degrade는 더 이상 허용되지 않는다.

---

## 3. 동작 방식

### 3.1 실행 모델 — 직접 수행과 필요한 분석만 위임

두 호스트 모두 메인이 역할 지침을 직접 수행한다. 독립 스펙·AST 분석의 분리 실익이 있을 때만 위임한다.
산출물은 _workspace에 저장하고 대상·필요 필드·경로만 전달한다. 공통 문서를 이미 읽은 문맥에서는 재읽지 않는다.

### 3.2 단계 흐름

설정·분석 → 리팩토링 권고와 시나리오 설계 → 함께 제시한 시나리오 승인 → 최초 생성 → 실행·커버리지·적합성 확인 순서다.
환경이 부족하면 필요한 변경에 동의받아 setup-harness로 준비하고 원래 작업을 재개한다. 재시작이 필요하면 재개 지점을 보존한다.
한 번의 테스트 실행에서 JUnit과 JaCoCo를 함께 만든다. 입력·범위·JDK·보고서 지문이 같을 때 결과를 공유한다.
보정은 실패 테스트→시나리오 불일치→커버리지 부족 순으로 한 묶음을 수행하고 반드시 6→8→9를 재검증한다.

### 3.3 리팩토링 권고

권고는 기록하고 대상을 기본 포함한다. 시나리오 승인에서 함께 확인하며 별도 포함/제외 질문을 하지 않는다.
운영 코드 리팩토링은 별도 요청 없이 수행하지 않는다.

### 3.4 실행 모드와 승인

| 모드 | LINE | BRANCH | METHOD | CLASS | 모든 원인을 합산한 보정 |
|---|---|---|---|---|---|
| 빠름 | 80% | 70% | 80% | 100% | 1회 |
| 균형(추천) | 90% | 80% | 90% | 100% | 3회 |
| 엄격 | 95% | 90% | 95% | 100% | 기존 무진전 종료 규칙 |

최초 설정에서 한 번 선택한다. 수치는 제품 정책이며 공식 권장값이 아니다. 정책 없는 기존 설정은 임계값·제외·반복 의미를 보존한다.
모드 변경을 명시할 때만 새 기본값을 적용하며 같은 요청의 직접 지정값이 우선한다.
모든 모드가 실제 테스트·JaCoCo·적합성과 시나리오 승인을 유지한다. 질문 도구 부재·취소·무응답을 승인으로 처리하지 않는다.
명시적 비대화형 입력의 기존 정책은 별도 기록하며 필수 값이 없으면 중단한다.

### 3.5 부분 재실행 · 상태 복원

[요청별 경로](../references/execution-policy.md)에 따라 조회는 빌드 없이, 테스트 실행은 자동 수정 없이, 커버리지 측정은 추가 생성 없이 처리한다.
자동 재개는 execution-budget.json을 유지한다. 빠름·균형에서 예산이 끝나면 검증 후 partial과 잔여를 반환한다.
사용자가 “계속 보정해줘”라고 명시해야 추가 예산이 생긴다. 조회·세션 재시작으로는 초기화하지 않는다.
strict/기존은 동일 실패·gap 3회 무진전, 적합성 최대 3라운드·동일 unmet 즉시 종료한다.


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
**Python 자체도 없어도 된다**(v0.15.0+, **전 OS** — macOS/Linux/WSL/Windows) — MCP·훅 진입점이
`node mcp/launch.cjs`(공식 훅 문서의 크로스플랫폼 패턴: exec form은 셸 미경유, node + 스크립트
경로는 전 플랫폼 동작)로 실행되며, PATH에 3.10+가 없으면(Windows는 `py -3`/`python`도 탐지)
uv(무-sudo; POSIX `install.sh` / Windows `install.ps1`)로 관리형 Python을 자동 설치한다
(`HARNESS_AUTO_PYTHON=0`으로 비활성화). POSIX 전용 구진입점 `mcp/run-server.sh`는 수동
폴백으로 유지된다. **훅 가드의 fail-open 계약**: Python이 끝내 해석되지 않으면 훅 스크립트
(record-run-context/redact-secrets)는 무동작 통과한다 — 구버전 `python3` 직접 호출과
동일한 계약이며, 세션 시작 화면의 remediation 안내(exit 2)로 복구한다. 자동 설치가 실패한
환경(오프라인 등)의 수동 폴백:

```bash
python3 -m pip install -r mcp/requirements.txt    # mcp[cli]>=2.2,<3, Python 3.10+
```

`setup-harness`의 자동 세팅 범위는 Python 런타임에 그치지 않는다 — **E6**이 `mcp/javaparser-cli`에서
`./mvnw -q -DskipTests package`(동봉된 Maven Wrapper, 시스템 Maven 불요)로 JavaParser jar를 자동
빌드하고, **E7**이 `scripts/setup_jdtls.py`로 JDT LS를 자동 설치한다(PATH → brew(macOS) →
eclipse.org milestone tarball). 두 단계 모두 v0.16.0부터 **필수**이며, 실패 시 remediation과 함께
하드 중단한다(silent degrade 없음). 최초 실행 1회는 Maven 의존성·`mvnw` 배포판·JDT LS tarball
다운로드를 위한 네트워크가 필요하다 — 오프라인 환경은 `REPO_AST_JAVAPARSER_JAR` 사전 지정 +
jdtls 사전 설치로 대체한다.

### 4.3 JavaParser AST 백엔드 (필수, v0.16.0+)

정밀 AST를 위해 jar 빌드가 **필수**다(JDK 21+). 시스템 Maven은 불요 — Maven Wrapper(`mvnw`)가
`mcp/javaparser-cli`에 동봉되어 있다. `.mcp.json` 기본값이 `REPO_AST_REQUIRE_JAVAPARSER=1`이라
jar가 없으면 대체 경로 없이 하드실패(`JAVAPARSER_REQUIRED`)한다. `setup-harness`의 E6이 자동 빌드하므로
보통 손으로 할 필요는 없다.

```bash
cd mcp/javaparser-cli && ./mvnw -q -DskipTests package     # → target/astcli-1.0.0-shaded.jar (리포 체크아웃 기준)
# 다른 위치의 jar를 쓰려면: export REPO_AST_JAVAPARSER_JAR=/abs/path/astcli-1.0.0-shaded.jar
```

설치본에서는 E6이 `${CLAUDE_PLUGIN_ROOT}` 앵커로 빌드한 뒤 `scripts/persist_astcli_jar.py`로
`${CLAUDE_PLUGIN_DATA}/javaparser/`에 복사한다 — 플러그인 캐시는 버전 키 스냅샷이라 업데이트마다
교체되므로, 이 영속 사본이 있어야 업데이트 후에도 jar가 살아남는다(탐색 순서: env →
`target/` → `${CLAUDE_PLUGIN_DATA}/javaparser/`).

### 4.4 JDT LS (필수, v0.16.0+)

semantic 분석 보강용. `jdtls`가 PATH에 있고 Java 21+ 런타임이 있으면 `.lsp.json`(node 경유
`mcp/jdtls-launcher.cjs`)으로 자동 연결된다. 없으면 `setup-harness` E7의 `scripts/setup_jdtls.py`가
PATH → brew(macOS) → eclipse.org milestone tarball(`${CLAUDE_PLUGIN_DATA}/jdtls`) 순으로 자동
설치를 시도하고, 그래도 실패하면 하드 중단한다 — AST-only degrade는 더 이상 허용되지 않는다.

> 위 4.2~4.4는 수동 명령이지만, 실제로는 **`/test-autoevermation-harness-plugin:setup-harness`가 감지해서
> 대화형이면 "지금 함께 세팅할까요?"로 묻고, CI면 결정적 항목(pip/mvnw/jdtls 설치)을 자동 수행**한다 — 보통 손으로
> 미리 할 필요가 없다. 자동 세팅이 실패하면(오프라인 등) 하드 중단 + remediation이 표시된다.
>
> **v0.24.0부터 환경 세팅은 `full-pipeline`이 아니라 `setup-harness`가 수행한다.** 플러그인 설치 후 최초 1회
> `/test-autoevermation-harness-plugin:setup-harness`를 실행하면 된다. `full-pipeline`/`configure-harness`는
> 시작 시 **검증(E-verify)만** 하고, 미완료면 필요한 변경 동의를 묶어 받고 setup-harness로 넘긴다. 준비 후 원래 작업을 재개한다.

### 4.5 제거

```text
# 플러그인만 제거
/plugin uninstall test-autoevermation-harness-plugin@test-autoevermation-harness

# 마켓플레이스 등록까지 해제 — 이 마켓플레이스에서 설치한 플러그인도 함께 제거된다(공식 동작)
/plugin marketplace remove test-autoevermation-harness
```

- 제거하지 않고 잠시 끄려면 `/plugin disable test-autoevermation-harness-plugin@test-autoevermation-harness`,
  다시 켜려면 같은 인자로 `/plugin enable`.
- 수동 설치(§4.1의 복사/symlink)를 사용한 경우에는 `~/.claude/plugins/test-autoevermation-harness-plugin`을
  삭제한 뒤 Claude Code를 재시작한다.
- 변경 사항은 `/reload-plugins` 또는 세션 재시작으로 반영된다.
- **상태줄 자동 원복**: 상태줄을 설치했다면 저장된 설치 경로의 manifest가 사라진 뒤 렌더할 때
  원래 상태줄로 복구된다. uninstall 후 캐시가 남으면 감지할 수 없다(§5.5의 self-heal). 즉시 원복하려면 uninstall 전에
  `/test-autoevermation-harness-plugin:setup-statusline`에 "제거"를 요청한다.

**완전 삭제(잔여 파일 정리):** `/plugin uninstall`은 설치 사본(`plugins/cache/`)과 레지스트리
항목만 지운다. 상태줄 전역 사본(`test-autoevermation-statusline.py`/`-launch.cjs`)과 전역
`settings.json`의 statusLine 원복은 §5.5 self-heal이 설치 파일 소실 후 처리하지만(캐시가 남아 있으면 명시적 제거 필요), 아래 항목은 남으므로 완전히 지우려면 수동 정리한다.

```bash
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# MCP venv·관리형 jdtls·JavaParser jar(v0.28.0+) 등 영속 데이터(수십 MB) — 업데이트에도
# 유지되도록 설계된 공식 플러그인 데이터 디렉터리(${CLAUDE_PLUGIN_DATA})라 uninstall이 지우지 않는다.
# 디렉터리 이름은 로드 방식에 따라 다르다(공식 규약: {plugin-id의 비영숫자 → '-'} —
# 마켓플레이스 설치는 `<플러그인>-<마켓>`, --plugin-dir 로드는 `<플러그인>-inline`, 구버전 사본은
# 접미사 없음). 설치 방식을 바꿔온 환경엔 여러 변형이 공존할 수 있으니 전부 정리한다:
rm -rf "$CFG/plugins/data/test-autoevermation-harness-plugin-test-autoevermation-harness" \
       "$CFG/plugins/data/test-autoevermation-harness-plugin-inline" \
       "$CFG/plugins/data/test-autoevermation-harness-plugin"

# 상태줄 설정 마커 — self-heal 후에도 cleaned=true 기록으로 남는다
rm -f "$CFG/test-autoevermation-statusline.json"

# 상태줄 설치 시 만든 settings.json 백업(있는 경우)
rm -f "$CFG"/settings.json.test-autoevermation-backup-*
```

대상 프로젝트의 산출물(생성 테스트 `src/test/java`, `test_docs/`, `_workspace/`, 빌드 파일에
주입된 JaCoCo 설정)은 사용자 자산이라 어떤 제거 절차도 건드리지 않는다. 이전 버전에서 대상 프로젝트에
추가된 선택 기능의 빌드·CI 설정도 자동 삭제하지 않으므로, 마이그레이션 시 해당 파일에서 직접 정리한다.
실행 산출물을 정리하려면 §4.6의 "하네스 실행 상태 재설정"을 따른다.

### 4.6 재설정

**최신 버전 반영(일반 재설정):**

```text
/plugin marketplace update test-autoevermation-harness
/reload-plugins
```

설치본은 버전 키 스냅샷(`plugins/cache/<마켓>/<플러그인>/<버전>/`)이라 소스 수정은 커밋+푸시+버전
bump+`update` 전에는 반영되지 않고, 실행 중 세션은 `/reload-plugins`(또는 재시작) 전에는 이전 버전을
계속 쓴다. 구버전 캐시는 CC가 orphan 처리 후 14일 뒤 자동 삭제한다. venv·JDT LS·JavaParser
jar(v0.28.0+)는 `${CLAUDE_PLUGIN_DATA}`에 있어 업데이트를 그대로 승계한다 — 단 v0.27.x 이하에서
올라온 직후에는 jar가 구버전 캐시에만 있었으므로 최초 1회
`/test-autoevermation-harness-plugin:setup-harness`를 재실행한다(E6이 영속 위치로 이관).

**설치 상태가 깨졌을 때(스킬 미노출·MCP 서버 에러 지속):** 이 플러그인의 캐시만 비우고 재설치한다
(`plugins/cache` 전체 삭제는 다른 플러그인까지 지우므로 피한다).

```bash
rm -rf ~/.claude/plugins/cache/test-autoevermation-harness
```

이후 Claude Code를 재시작하고 §4.1 설치 절차를 다시 실행한다.

**하네스 실행 상태 재설정:** 파이프라인 중간 산출물은 대상 프로젝트 루트의 `_workspace/`에 저장된다
(부분 재실행의 기반, §3.5). **예산 파일은 보존한다. 그 외 중간 산출물이 없어도** 영속 증거(생성 테스트 `src/test/java`, 승인 시나리오
`test_docs/scenarios/*.md`, 커버리지/JUnit 리포트)가 남아 있으면 다음 실행은 처음이 아니라
`detect_pipeline_state`가 판정한 단계부터 **재개**된다(§3.5 신호 2). 완전한 초기화(0단계 `configure-harness`
인터뷰부터)를 원하면 `src/test/java`의 생성 테스트와 `test_docs/`까지 함께 정리해야 한다. 새 입력으로 다시
돌리면 기존 `_workspace/`는 자동으로 `_workspace_legacy_{YYYYMMDD_HHMMSS}/`로 보존된다. `test_docs/`는 사람이 읽는 영속
산출물이라 보통 유지한다(§7).
상태줄을 설치했다면 `/test-autoevermation-harness-plugin:setup-statusline`에 "제거"를 요청해 원복한다(§5.5).

---

## 5. 사용법

### 5.1 빠른 시작 (대화형)

Spring 프로젝트를 연 Claude Code 세션에서:

```text
/test-autoevermation-harness-plugin:full-pipeline
```

이후 하네스가 묻는 것들(전형적 순서):

1. **(사전) `setup-harness`**: 미충족 환경 항목별 "지금 함께 세팅할까요?" (MCP SDK 설치, jar 빌드, JDT LS 설치 등) — `full-pipeline`은 이 세팅이 끝나 있어야 시작된다(E-verify 게이트)
2. **0.5**: Boot 버전을 감지 못했거나 충돌하면 메이저 버전/우선 기준 선택
3. **0.6**: JaCoCo XML 리포트 능력을 확인하고, 필요한 경우 스니펫 주입 여부와 콜드 캐시 프라이밍을 결정한다.
4. **인터뷰 3항목**: 스펙 문서 경로 / 테스트 대상 / 커버리지 임계값·제외
5. **3.5 게이트**: 리팩토링 권고가 있으면 "전체 포함(권장) / 일부 제외 / 전체 제외"
6. **4.5 게이트**: 시나리오 "전체 승인 / 일부 제외·수정 / 재설계 요청"
7. 완료 후 **Markdown 보고서** + `test_docs/` + 생성 테스트 확인

"스프링 테스트 생성해줘", "커버리지 더 올려", "시나리오 다시 검증해줘" 같은 자연어도 스킬 트리거로 인식된다
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

`claude -p`로 호출하면 `AskUserQuestion` 호출이 차단되므로 인터뷰·게이트가 비대화형 정책으로 대체된다(§3.4). **미지정 필수 입력은 하드 중단**되므로
`HarnessRequest`를 채워서 호출한다(하네스 자체는 JDK 21+가 필요하다 — E4):

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

- 빌드 파일 자동 주입 금지 → JaCoCo XML 설정은 미리 반영한다.
- 기본 오프라인 → 캐시가 비어 있으면 사전 워밍업(예: `mvn dependency:go-offline`)을 해 두거나
  `BUILD_TEST_ALLOW_NETWORK=1`을 옵트인한다.
- GitHub Actions 예제 [examples/ci/gradle-ci.yml](../examples/ci/gradle-ci.yml) · [maven-ci.yml](../examples/ci/maven-ci.yml)는 **대상 프로젝트의 빌드·테스트 워크플로**(생성된 테스트를 CI에서 돌리는 쪽)이며 하네스(`claude -p …full-pipeline`)를 호출하지 않는다. 하네스를 CI에서 돌리려면 위 `claude -p` 명령을 별도 step으로 추가하고 `setup-harness`를 선행한다.

### 5.4 이어서 작업하기 (부분 재실행)

같은 프로젝트에서 다시 부르면 `_workspace/`를 감지해 필요한 단계만 돈다: "이 패키지만 다시",
"임계값 바꿔서 다시", "테스트 실패 고쳐" 등(§3.5 표). **`_workspace/`가 없어도**(fresh clone·새 세션 등)
생성 테스트·승인 시나리오·리포트가 남아 있으면 `detect_pipeline_state`가 재개 단계를 판정하므로 처음부터
다시 돌지 않는다 — 자세한 시나리오는 §5.6 FAQ. 도메인 특화 설정을 재사용하려면 configure-harness 마지막의
**도메인 스킬 스캐폴딩**으로 `/test-autoevermation-harness-plugin:<custom>` 스킬을 만들어 둘 수 있다.

### 5.5 상태줄 진행률 표시 (자동)

Claude Code 상태줄에 플러그인 버전과 full-pipeline 진행률이 한 줄 추가된다(기존 상태줄 출력은
그대로 유지):

```text
[Test-AutoEverMation#<version>]                                    ← 파이프라인 없음(버전만; plugin.json에서 동적으로 읽음)
[Test-AutoEverMation#<version>] <progress>% | stage 4: generate-scenarios  ← 진행 중(_workspace/ 산출물 기반)
[Test-AutoEverMation#<version>] <progress>% | ↩ resumed @ stage 8: measure-coverage  ← 영속 증거로 재개(_workspace/_resume.json, 표시 stage를 재진입 지점으로 clamp)
[Test-AutoEverMation#<version>] 100% | done (ok)                   ← 완료(pipeline_result.json의 status)
```

**자동 설치·제거.** Claude Code 플러그인은 install/uninstall 라이프사이클 훅이 없고, 플러그인
settings로는 main statusLine을 설정할 수 없다(공식: `agent`/`subagentStatusLine`만 적용). 그래서
전역 사본 방식으로 자동화한다:

- **설치**: 설치 후 첫 세션에서 `SessionStart` 훅(`hooks/statusline-autosetup.py`)이 어시스턴트에게
  "상태줄을 설치할까요?"를 **한 번** 묻게 한다(AskUserQuestion). 승인하면 wrapper·런처를
  `${CLAUDE_CONFIG_DIR:-~/.claude}/`에 복사하고 `settings.json`의 `statusLine`을 런처로 점유하며,
  기존 커맨드는 `test-autoevermation-statusline.json`에 delegate로 보존한다. 이후 세션부터는 매
  시작마다 조용히·멱등하게 갱신되고, OMC HUD 등이 슬롯을 되가져가도 **자동 재점유**한다(이중
  래핑 금지). 표시 범위는 모든 세션(파이프라인 없는 프로젝트에선 버전만).
- **제거(self-heal)**: `/plugin uninstall`은 전역 `settings.json` 수정을 되돌리지 않으므로, 전역
  런처가 가리키는 wrapper 사본이 렌더마다 플러그인 설치 여부를 확인한다. 해당 설치 경로의 manifest가 사라지면
  1회 한정으로 `settings.json`을 delegate(원래 상태줄)로 원복하고 전역 사본을 정리한다 → 다음 렌더에서 복구. 캐시가 남아 있으면 제거를 감지할 수 없다. 즉시 원복은 `setup-statusline`에 "제거" 요청.
- **끄기**: 최초 확인에서 "설치 안 함"을 고르거나 환경변수 `TAM_STATUSLINE_AUTO=0`으로 자동
  설치를 비활성화한다(CI 권장).

진행률은 프로젝트 루트 `_workspace/`의 단계 산출물(§3.2) 존재 여부로 계산한다 — 읽기 전용,
파이프라인 비침습. 상세: [skills/setup-statusline/SKILL.md](../skills/setup-statusline/SKILL.md).

### 5.6 자주 묻는 질문 (이어하기 · 결과 개선)

“결과만 보여줘”는 기존 결과와 신선도를 보고한다. “실행해줘”는 한 번 실행하고 자동 수정하지 않는다.
“커버리지 측정해줘”는 유효 결과 공유 또는 한 번 실행·측정한다. “부족한 커버리지를 올려줘”는 승인 대상과 저장 예산 안에서 보정한다.
partial이면 executionSummary.stopReason과 미해결 항목을 확인한다. 명시적인 계속 요청으로만 보정 예산을 추가한다.
설정을 매번 다시 입력할 필요는 없다. 프로젝트용 호출 스킬은 저장 요청이 있을 때만 만든다.


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
| `maxRepairRetries` | `3` | 보정 루프 진전 추적 단위(상한 아님 — #12 무진전 "3회 연속"과 정렬) |
| `domainKeywords` | `[]` | 스펙 검색 힌트 |
| `refactorAdvisory` | `{enabled: true}` | 3.5단계 제어. `thresholds{cyclomatic:10, constructorArgs:7}` 오버라이드 가능 |

미지정 필드는 **자동 기본값으로 채우지 않는다**(fallback-policy #13) — 대화형은 질문, CI는 중단.

### 6.2 HarnessConfig (0단계 산출)

인터뷰 + HarnessRequest + 감지 결과가 병합된 실행 설정. 핵심 블록:

- `springProfile{bootVersion, namespace, junitEngine, mockAnnotation, mockImport, javaBaseline, …}` — 0.5단계 확정
- `coverage{line:0.95, branch:0.90, method:0.95, class:1.00, excludes[...]}` — 기본 제외:
  `**/*Application*`, `**/config/**`, `**/dto/**`, `**/generated/**`
- `coverageMaxIterations`(기본 3 — 진전 추적 단위)
- `refactorAdvisory{enabled, thresholds}` (인터뷰 항목 아님 — HarnessRequest로만 오버라이드)

전체 스키마 정본: [configure-harness/SKILL.md](../skills/configure-harness/SKILL.md) 「4단계: HarnessConfig 생성」.

### 6.3 환경변수 (.mcp.json / opt-in)

| 변수 | 기본 | 의미 |
|---|---|---|
| `REPO_AST_ALLOW_ROOT` | `${CLAUDE_PROJECT_DIR}` | repo-ast 경로 allowlist 루트(밖은 거부) |
| `REPO_AST_JAVAPARSER_JAR` | 자동 탐색 | JavaParser CLI jar 경로 지정 |
| `REPO_AST_REQUIRE_JAVAPARSER` | **`1`**(`.mcp.json` 기본값) | **v0.31.0부터 no-op** — 정규식 fallback을 삭제해 값과 무관하게 jar 부재는 항상 `JAVAPARSER_REQUIRED` 하드실패. 설정 호환성을 위해서만 남겨둠 |
| `REPO_AST_JAVA_BIN` | `java` (PATH) | JavaParser CLI 실행에 쓸 `java` 바이너리 경로 지정 |
| `SPEC_DOC_ALLOWLIST` | `docs,specs,requirements` | spec-doc이 읽을 수 있는 하위 디렉터리 |
| `SPEC_DOC_REDACT` | `on` | 민감정보 마스킹 |
| `SPEC_DOC_REDACT_EMAIL` | `on` | EMAIL 마스킹만 개별 해제(`off`) — 스펙의 예시 이메일을 테스트 fixture로 그대로 써야 할 때 |
| `SPEC_DOC_WORKSPACE` | `${CLAUDE_PROJECT_DIR}` | spec-doc 경로 봉쇄 루트 |
| `BUILD_TEST_ALLOW_NETWORK` | `0` | 테스트 실행 네트워크(옵트인, CI 프라이밍용) |

> `TEST_AUTOEVERMATION_HARNESS_NETWORK`·`TEST_AUTOEVERMATION_HARNESS_TEST_SCOPE`는 v0.29.0에서
> 제거됐다 — 유일한 소비자였던 `guard-network.py`/`guard-read.py` 삭제로 죽은 변수가 됐다.
> 테스트 실행 네트워크 제어는 `BUILD_TEST_ALLOW_NETWORK` 하나로 일원화된다.

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
  `scenarioRef`/`criteriaRef` — 9단계 적합성 검증이 이 링크로 매핑한다.
- 본문: `// given` → `// when`(단일 행위) → `// then` 3단, stub은 BDDMockito `given().willReturn()`,
  Jupiter 프로파일은 `@DisplayName` 한국어 행위 서술.
- 상태 판정: 시나리오 전부 satisfied → `status: ok`, unmet 존재/무진전 중단 → `partial`(잔여 전량 보고),
  환경/전제 실패 → `failed`(remediation 포함). **임의 제외·침묵 누락 없음.**

---

## 8. 보안 모델

| 항목 | 구현 |
|---|---|
| 의존성 오프라인 기본 | build-test MCP 서버가 `BUILD_TEST_ALLOW_NETWORK=0`(`.mcp.json` 기본값)을 읽어 gradle `--offline`/maven `-o`를 강제. 유일한 예외는 사용자가 승인한 1회 캐시 프라이밍(`online=True`) |
| 경로 allowlist | repo-ast `REPO_AST_ALLOW_ROOT`(프로젝트 루트 밖 경로 거부), spec-doc `SPEC_DOC_ALLOWLIST`+`SPEC_DOC_WORKSPACE`(허용 디렉터리 밖 문서 거부) — MCP 서버 입력 경계이며, 도구 수준 Read deny(vendor/build/generated)는 없다 |
| 소스 노출 최소화 | repo-ast는 메서드 본문 미반환(구조 메타만), 에이전트 결과에 소스 원문 금지 |
| 민감정보 | `redact-secrets.py` 훅 + spec-doc redaction (토큰·이메일·접속문자열) |
| 쉘 안전 | `run_targeted_tests`가 shlex로 인자 escaping 강제 |
| 에이전트 권한 | frontmatter `tools:` 최소 권한(§2.3) — read-only 판정 에이전트는 Write/Bash 불가 |

---

## 9. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| MCP 서버 3종이 연결 안 됨 | (자동 설치 실패 — 오프라인/`node` 부재/`HARNESS_AUTO_PYTHON=0`) | **세션 시작 화면에 표시된 수동 폴백 명령**(v0.13.1+, SessionStart 훅 exit 2 안내)을 따른다: Python 3.10+ 설치 → `python3 -m pip install -r mcp/requirements.txt` (Windows: `py -3 -m pip ...`) → `/reload-plugins`. 상세 진단은 `mcp-logs-plugin-*` 로그의 `launch`/`bootstrap` 줄 |
| `E3b`/E-verify에서 하드 중단(`health` 3종 호출 실패) | 플러그인 비활성/MCP 서버 미등록/세션에 도구 미노출 | `/test-autoevermation-harness-plugin:setup-harness` 실행 → 그래도 실패하면 플러그인 활성화 여부 확인 → `node mcp/launch.cjs --ensure-only` 수동 실행 → `/reload-plugins`(또는 Claude Code 재시작) |
| 플러그인 스킬이 아예 안 보임 / 설치 상태가 깨짐 | 플러그인 캐시 손상 | 이 플러그인 캐시만 삭제: `rm -rf ~/.claude/plugins/cache/test-autoevermation-harness` → Claude Code 재시작 → 재설치(§4.6). `plugins/cache` 전체 삭제는 다른 플러그인까지 지우므로 피한다 |
| `JAVAPARSER_REQUIRED`로 하드 중단 | JavaParser jar 빌드 실패/JDK 21+ 없음 | §4.3대로 `./mvnw -q -DskipTests package` 재시도 또는 `REPO_AST_JAVAPARSER_JAR` 사전 지정. JDK 21+ 미탐지가 원인이면 먼저 JDK를 설치 |
| `java -version`가 21 미만/미탐지로 `setup-harness`(E4) 중단 | JDK 21+ 미설치 또는 PATH에 구버전 JDK만 존재 | JDK 21+ 설치 후 PATH 갱신(jar 빌드 17+ ⊂ JDT LS 21+를 아우르는 단일 기준) — E10(대상 프로젝트 테스트 실행 JDK)과는 별개 |
| 커버리지(8)가 리포트를 못 찾음 | Gradle JaCoCo XML 기본 OFF | 0.6단계 JaCoCo 주입 승인 또는 provisioning 스니펫 반영 |
| 첫 실행(6)에서 의존성 해석 실패 | 콜드 캐시 + 기본 오프라인 | 1회 온라인 프라이밍 승인 / CI는 사전 `dependency:go-offline` 또는 `BUILD_TEST_ALLOW_NETWORK=1` |
| Mockito mock 생성 실패 (JDK 24/25) | inline mock-maker ↔ 신형 JDK 비호환 | 실행 JDK를 17/21 LTS로, 또는 Mockito 5.16+(ByteBuddy 1.17+), 또는 `-Dnet.bytebuddy.experimental=true` (E10) |
| `BUILD_TOOL_UNDETECTED` | wrapper/빌드파일 미감지 | 대화형은 질문에 답, CI는 `HarnessRequest.buildTool` 명시 |
| `INTERVIEW_REQUIRED`/`PROFILE_CONFLICT`로 중단(CI) | Boot 버전 미감지·빌드파일↔소스 불일치 | `HarnessRequest.springVersion` 명시(가정 생성 방지를 위한 의도된 중단) |
| `@MockBean`/`@MockitoBean` 컴파일 에러 | 프로파일 오버라이드로 버전과 불일치 | 0.5단계 감지값 확인 — Boot ≤3.3은 `@MockBean`, 3.4+는 `@MockitoBean`([version-compatibility.md](../references/version-compatibility.md)) |
| `status: partial`로 종료 | unmet 시나리오/무진전 3회/전량 제외 등 | 보고서의 잔여 목록·사유 확인 → "테스트 실패 고쳐"/"커버리지만 더 올려" 등으로 부분 재실행 |
| JDT LS 설치 실패로 하드 중단 | `jdtls` 자동 설치(brew/tarball) 실패, PATH·JDT LS 미인식, 또는 Java 21 미만 | §4.4대로 `jdtls` + Java 21+를 수동 설치하거나 `scripts/setup_jdtls.py` 로그 확인. 오프라인이면 jdtls 사전 설치 후 재시도 |

---

## 10. 문서 지도

| 문서 | 역할 |
|---|---|
| [README.md](../README.md) | 요약 소개·설치·표 위주 레퍼런스 |
| **GUIDE.md (이 문서)** | 동작 원리·사용법 종합 가이드 |
| [docs/pipeline-flow.md](./pipeline-flow.md) | 전체 흐름 Mermaid 다이어그램 |
| [skills/full-pipeline/SKILL.md](../skills/full-pipeline/SKILL.md) | 오케스트레이션 정본(단계별 Agent 호출·실패표) |
| [skills/full-pipeline/references/orchestration-detail.md](../skills/full-pipeline/references/orchestration-detail.md) | `_workspace/` 규약·부분 재실행 매트릭스·timing |
| [references/environment-setup.md](../references/environment-setup.md) | 환경 세팅 체크리스트(E1~E12) + **E-verify 검증 프로브** SSOT |
| [references/fallback-policy.md](../references/fallback-policy.md) | fallback 정책 SSOT |
| [references/scenario-docs.md](../references/scenario-docs.md) | `test_docs/`·승인·적합성 검증 SSOT |
| [references/refactor-advisory.md](../references/refactor-advisory.md) | 3.5단계 판정 기준·임계값 SSOT |
| [references/build-provisioning.md](../references/build-provisioning.md) | JaCoCo XML 주입·캐시 프라이밍 SSOT |
| [references/version-compatibility.md](../references/version-compatibility.md) | Boot 2.0–4.x 프로파일별 전체 코드 템플릿 |
| [references/custom-components.md](../references/custom-components.md) | 커스텀 스테레오타입 인식 규칙 |
| [references/agent-result-envelope.md](../references/agent-result-envelope.md) | 11개 서브에이전트 공통 결과 봉투(status/summary/evidence/warnings/errors/nextActions) |
| [references/test-code-invariants.md](../references/test-code-invariants.md) | 생성 테스트 코드 불변식(프로파일별 import·애노테이션·금지 패턴) |
| [RESEARCH_NOTES.md](../RESEARCH_NOTES.md) | 핀 고정 버전·API·공식문서 근거(런타임 SSOT) |
| [DEPENDENCIES.md](../DEPENDENCIES.md) | OMC 비의존 선언·런타임 의존성 표 |
| [CHANGELOG.md](../CHANGELOG.md) | 버전별 변경 이력 |
| [examples/](../examples/) | 프로파일별 테스트/빌드/CI 예제 13종 |

상태줄 설치 경로와 버전은 공식 SessionStart 훅이 실행된 플러그인 루트로 갱신한다. 비공개 설치 레지스트리는 읽지 않는다. 자동 원복은 해당 경로의 manifest가 사라진 뒤 동작한다. 제거 후 캐시가 남아 있으면 감지할 수 없으므로, 즉시 원복하려면 제거 전에 `setup-statusline`에서 제거를 요청한다.
