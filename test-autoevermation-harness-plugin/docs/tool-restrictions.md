# 도구 제약 전수 감사 (Tool Restriction Audit)

> **한 줄 요약 (v0.30.0)**: 이 플러그인이 **사용자 세션의 도구 호출을 차단할 수 있는 지점은 단 한 곳** —
> `record-run-context.py`의 4.5 승인 게이트(`Task|Agent` 매처)뿐이며, 그것도 하네스 파이프라인이 활성인
> 세션에서만 발동한다. `Read`·`Write`·`Edit`·`WebFetch`·`WebSearch`·`Bash`를 막는 것은 **없다**.

이 문서는 "하네스 때문에 뭐가 막히나?"라는 질문에 매번 소스를 뒤지지 않도록, 플러그인이 도구를 제약할 수
있는 **모든 경로**를 등급별로 정리한다. 각 항목은 실제로 차단력이 있는지, 언제 발동하는지, 근거 파일이
무엇인지를 명시한다.

---

## 0. 판정 기준 — 무엇이 "차단"인가

Claude Code 공식 계약상 **도구 실행을 실제로 막을 수 있는 훅 이벤트는 `PreToolUse` 하나뿐이다.**

| 이벤트 | 차단 가능 | 근거 |
|---|---|---|
| `PreToolUse` | **가능** | `hookSpecificOutput.permissionDecision`이 `allow`/`deny`/`ask`/`defer` |
| `PostToolUse` | **불가능** | 도구 실행 **후** 발화 — 공식문서: "the tool already ran". `decision: "block"`은 후속 진행만 멈추고 이미 일어난 동작을 되돌리지 못한다 |

출처: [Hooks reference](https://code.claude.com/docs/en/hooks)

따라서 아래에서 **Tier 1만 진짜 차단**이고, Tier 2~5는 차단처럼 보이지만 차단이 아니다. 이 구분이 이
문서의 존재 이유다 — 과거 `settings.json`의 `WebFetch` deny 항목이 "이 플러그인이 웹을 막는다"는 오해를
반복 생산했고, v0.30.0에서 삭제됐다.

---

## Tier 1 — 실제로 차단하는 것 (PreToolUse deny)

### 1.1 `scripts/record-run-context.py` — 4.5 시나리오 승인 게이트

| 항목 | 값 |
|---|---|
| 매처 | `Skill\|Task\|Agent` (PreToolUse) |
| 차단 대상 | `test-code-generator` 서브에이전트 **스폰** |
| 발동 조건 | `_workspace/.markers/run.json`의 `session_id`가 현재 세션과 일치(= 하네스 파이프라인 활성) **그리고** `04_scenario_set.json` 또는 `04b_approval.json` 부재 |
| 비파이프라인 세션 | 발동 **안 함** (`run.json` 부재 → `_run_active()` false) |
| 우회 | 4단계(`scenario-generator` 위임) 수행 → `test_docs/scenarios/*.md` 저장 → `AskUserQuestion` 승인 → `04b_approval.json` 기록 |

**존치 이유**: 사용자가 승인하지 않은 시나리오로 테스트 코드가 생성되는 것은 하네스의 핵심 계약 위반이다.
쓰기 도구와 무관하고 발동 범위가 파이프라인 내부로 한정되므로 v0.30.0 차단 해제 대상에서 제외했다.

**이 훅의 다른 동작은 전부 비차단**이다: `run.json` / `spawn-<agent>.json` /
`pipeline-state.detected.json` 마커 기록과 `additionalContext` 단계 계약 리마인더 주입.

---

## Tier 0 — v0.30.0에서 제거된 것 (이력)

### 0.1 `scripts/guard-gate-artifacts.py` — PreToolUse(`Write|Edit`) 등록 해제

v0.22.0~v0.29.0 동안 `Write`/`Edit`를 가로채 다음을 `deny`했다:

- **Zone A** `_workspace/**` 단계 산출물 — `.markers/**` 쓰기, 위임 증거 없는 산출물 기록, 순서 게이트
  위반, 8단계 커버리지 필드 불변식(#21) 위반. **`_workspace` 경로면 파이프라인 비활성이어도 발동**
- **Zone B** `src/test/java/**` — 04/04b 미승인, 허용 에이전트 외 기록 (run-active 한정)
- **Zone C** `test_docs/**` — 선행 산출물 없는 문서 기록 (run-active 한정)

**해제 사유**: 하네스를 쓰지 않는 일반 개발 세션에서도 Zone A가 발동했고, 사용자가 의도적으로 인라인
수정하려는 정당한 경우까지 봉쇄했다. 계약 위반을 막는 값보다 정상 작업을 가로막는 비용이 컸다.

**현재 상태**: `hooks/hooks.json`에서 엔트리 삭제. 스크립트 파일은 **존치**하며 zone 판정 로직은
`tests/test_pipeline_v2.py`가 계속 검증하지만, 도구 경로에 연결되지 않아 실행되지 않는다.

### 0.2 `guard-read.py`(Read·WebFetch) / `guard-network.py`(Bash) — v0.29.0에서 파일 삭제

보호 대상인 서브에이전트는 이미 `agents/*.md`의 `tools:`로 제한되는데(WebFetch/WebSearch 보유
에이전트 **0개**) 훅은 하네스와 무관한 세션까지 차단하면서 Read 호출당 ~54ms를 물렸다.

### 회귀 방지

| 테스트 | 검사 내용 |
|---|---|
| `test_no_pretooluse_hook_can_block_a_write` | PreToolUse 매처에 `Write`/`Edit` 부재 + `guard-gate-artifacts.py` 미등록 |
| `test_write_hooks_are_post_tool_use_and_warn_only` | `Write\|Edit`에 남은 훅이 PostToolUse이고 `--mode warn`인지 |
| `test_guard_scripts_are_deleted` | `guard-read.py`·`guard-network.py` 파일 부재 |
| `test_hooks_json_has_no_read_or_bash_matcher` | `Read\|WebFetch`·`Bash` 매처 부재 |

---

## Tier 2 — 차단처럼 보이지만 차단력이 없는 것

### 2.1 `scripts/redact-secrets.py` (PostToolUse `Write|Edit`, `--mode warn`)

쓰기가 **끝난 뒤** 실행되므로 구조적으로 차단 불가. `warn` 모드는 매치를 **보고만** 하고 파일을 수정하지
않는다(파일 수정은 `strip` 모드 전용이며 훅에서 쓰지 않는다). 탐지 대상: API 키·토큰, 패스워드, JDBC
URL, AWS 키, PEM 블록, 이메일, Authorization 헤더.

### 2.2 `settings.json`의 `permissions`

공식문서가 명시: 플러그인 `settings.json`은 **`agent`와 `subagentStatusLine` 키만 적용된다.**

> **Settings** | `settings.json` | Default configuration applied when the plugin is enabled.
> Only the `agent` and `subagentStatusLine` keys are currently supported
> — [Plugins reference](https://code.claude.com/docs/en/plugins-reference)

즉 여기 어떤 `permissions.deny`를 써도 **아무 효과가 없다.** v0.30.0에서 오해 방지를 위해 deny 목록
(`Read(.env/*.pem/secrets/build/target/node_modules)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`)을
전부 삭제하고 `allow`만 남겼다. 남은 `allow`는 승인 프롬프트를 **줄이는** 사전승인이라 차단과 무관하다.

이 자세를 원하는 사용자는 해당 블록을 자기 `.claude/settings.json` 또는 `~/.claude/settings.json`에
복사해야 한다 — 사용자 settings에서는 실제로 적용된다.

### 2.3 존재하지 않는 컴포넌트

플러그인에 `bin/`(Bash PATH 주입)과 `monitors/`(백그라운드 모니터)는 **없다**. 도구 표면에 영향을 주는
경로가 아니다.

---

## Tier 3 — 서브에이전트 내부 한정 (메인 세션과 무관)

`agents/*.md` frontmatter의 `tools:`(allowlist)와 `disallowedTools:`(denylist)는 **해당 서브에이전트가
자기 컨텍스트 안에서 쓸 수 있는 도구**만 정한다. 사용자의 메인 세션에는 아무 영향이 없다.

공식 계약:
- `tools` 생략 시 서브에이전트가 쓸 수 있는 모든 도구 상속
- 둘 다 있으면 `disallowedTools`가 **먼저** 적용되고 남은 풀에 `tools`가 해석됨
- 플러그인 서브에이전트는 `hooks`/`mcpServers`/`permissionMode`를 **무시**(보안상 제약)

출처: [Sub-agents](https://code.claude.com/docs/en/sub-agents)

| 에이전트 | `disallowedTools` | 비고 |
|---|---|---|
| `ast-structure-analyzer` | Write, Edit, Bash | 읽기 전용 |
| `source-code-analyzer` | Write, Edit, Bash | 읽기 전용 |
| `spec-reviewer` | Write, Edit, Bash | 읽기 전용 |
| `refactor-advisor` | Write, Edit, Bash | 읽기 전용 |
| `scenario-generator` | Write, Edit, Bash | 읽기 전용 |
| `test-code-generator` | Bash | 쓰기 O, 실행 X |
| `coverage-closer` | Bash | 쓰기 O, 실행 X |
| `test-editor` | Bash | 쓰기 O, 실행 X |
| `scenario-conformance-verifier` | Bash | 쓰기 O, 실행 X |
| `test-runner` | Write, Edit | 실행 O, 쓰기 X |
| `test-fixer` | *(없음)* | 쓰기 + Bash 모두 보유 |

**주목**: 11종 중 `WebFetch`/`WebSearch`를 `tools:`에 가진 에이전트는 **0개**다. 즉 하네스 서브에이전트는
애초에 웹에 접근하지 않는다 — 이것이 v0.29.0에서 `guard-read.py`의 WebFetch deny를 "보호 대상 없음"으로
판정해 삭제한 근거다.

---

## Tier 4 — 도구 차단이 아닌 MCP 런타임 제약

`.mcp.json`의 환경변수는 **플러그인 자체 MCP 도구의 동작 범위**를 정하며, 사용자의 `Read`/`Bash`에는
영향을 주지 않는다.

| 변수 | 기본값 | 효과 |
|---|---|---|
| `REPO_AST_ALLOW_ROOT` | `${CLAUDE_PROJECT_DIR}` | repo-ast MCP가 프로젝트 루트 밖을 파싱하지 못하게 하는 샌드박스 루트 |
| `REPO_AST_REQUIRE_JAVAPARSER` | `1` | jar/JDK 미비 시 정규식 fallback 없이 **하드 실패**. 차단이 아니라 품질 게이트 |
| `SPEC_DOC_ALLOWLIST` | `docs,specs,requirements` | spec-doc MCP의 인덱싱 대상 디렉터리 |
| `SPEC_DOC_REDACT` | `on` | 스펙 인덱싱 결과의 시크릿 마스킹 |
| `BUILD_TEST_ALLOW_NETWORK` | `0` | `gradle --offline` / `mvn -o` 플래그 부착. **빌드 CLI 플래그이지 도구 차단이 아니다** |

`BUILD_TEST_ALLOW_NETWORK`는 "테스트 실행이 네트워크를 타지 않는다"를 보장하는 실질 장치이며, 훅과
독립적으로 동작한다. 옵트인하려면 `1`로 설정한다.

---

## Tier 5 — 프롬프트 문구 (강제력 없음)

`skills/*/SKILL.md` 15개 파일에 "금지"·"차단" 서술이 있다. 이는 LLM에게 주는 **지시**이지 물리적
강제가 아니다. v0.18의 원칙 — *"LLM prose는 강제가 아니다"* — 가 그대로 적용된다. 실제 강제는 Tier 1의
훅 한 곳뿐이며, 나머지 계약 준수는 `_workspace/.markers/` 증거와 사후 검증에 의존한다.

---

## 부록 — 내 세션에서 실제로 무엇이 걸리는지 확인하는 법

설치본과 레포 워킹트리가 다를 수 있다(설치본은 git 커밋 고정 클론이라, 커밋·푸시·`/plugin update`
전에는 레포 변경이 반영되지 않는다).

```bash
# 실제 실행 중인 설치본의 훅 구성 확인
python3 -c "
import json,glob
for f in glob.glob('$HOME/.claude/plugins/marketplaces/*/test-autoevermation-harness-plugin/hooks/hooks.json'):
    h=json.load(open(f))
    print(f)
    print('  PreToolUse :', [e.get('matcher') for e in h['hooks'].get('PreToolUse',[])])
    print('  PostToolUse:', [e.get('matcher') for e in h['hooks'].get('PostToolUse',[])])
"
```

`PreToolUse`에 `Write|Edit`가 보이면 **아직 v0.29.0 이하**다 — `/plugin update` 후 `/reload-plugins`가
필요하다. 훅 변경은 세션 시작 시점에 로드되므로 `/reload-plugins` 없이는 이전 버전 경로를 계속 쓴다.

---

## 참고 문서

- [Hooks reference](https://code.claude.com/docs/en/hooks) — PreToolUse/PostToolUse 차단 계약
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — 플러그인 `settings.json` 적용 범위
- [Sub-agents](https://code.claude.com/docs/en/sub-agents) — `tools`/`disallowedTools` 의미론
- [docs/GUIDE.md](./GUIDE.md) §2.5 — 훅 구성과 변경 이력
- [references/fallback-policy.md](../references/fallback-policy.md) — degrade 금지 정책(#2·#3·#20·#21)
