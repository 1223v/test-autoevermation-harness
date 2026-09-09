# 도구 제약 전수 감사 (Tool Restriction Audit)

> **한 줄 요약 (v0.32.0)**: 차단 지점은 **PreToolUse 훅 2개**뿐이고, **둘 다 하네스 파이프라인이
> 이 세션에서 실제로 도는 동안에만** 발동한다(`_workspace/.markers/run.json` 기준).
> 파이프라인을 쓰지 않으면 `Read`·`Write`·`Edit`·`WebFetch`·`WebSearch`·`Bash` 무엇도 막히지 않는다.

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

### 1.1 `scripts/guard-gate-artifacts.py` — 산출물 무결성·순서 게이트

| 항목 | 값 |
|---|---|
| 매처 | `Write\|Edit` (PreToolUse) |
| **전제 조건** | `_workspace/.markers/run.json`의 `session_id` == 현재 세션. **아니면 경로·내용과 무관하게 전부 allow** |
| Zone A `_workspace/**` | `.markers/**` 위조, 위임 증거 없는 산출물, 순서 게이트 위반, 8단계 커버리지 필드 불변식(#21) 위반 |
| Zone B `src/test/java/**` | 04/04b 승인 전 기록, 허용 에이전트(`test-code-generator`·`coverage-closer`·`test-fixer`·`test-editor`) 외 기록 |
| Zone C `test_docs/**` | 선행 산출물 없는 문서 기록 |

**존치 이유**: `fallback-policy.md #21`(커버리지 게이트 무효 조건)과 단계 순서 계약을 기계로 강제하는
유일한 장치다. prose는 강제가 아니라는 v0.18 원칙이 그대로 적용된다.

**이력**: v0.22.0 도입 시 Zone A와 markers 검사에 run-active 게이트가 **없어서** 하네스와 무관한
세션에서도 `_workspace/` 편집이 막혔다. 그 오탐 때문에 v0.30.0에서 등록 해제, v0.31.0에서 파일까지
삭제했으나 #21·순서 계약이 기계 검증을 잃었다. **v0.32.0에서 게이트를 전 Zone에 적용해 복원**했다 —
막아야 할 것만 막는다. 회귀 방지: `test_non_pipeline_session_is_never_blocked`,
`test_same_paths_are_guarded_once_the_run_is_active`, `test_write_guard_judges_nothing_outside_an_active_run`.

### 1.2 `scripts/record-run-context.py` — 4.5 시나리오 승인 게이트

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

## Tier 0 — 삭제된 훅 (이력)

### 0.1 `guard-read.py`(Read·WebFetch) / `guard-network.py`(Bash) — v0.29.0에서 파일 삭제

보호 대상인 서브에이전트는 이미 `agents/*.md`의 `tools:`로 제한되는데(WebFetch/WebSearch 보유
에이전트 **0개**) 훅은 하네스와 무관한 세션까지 차단하면서 Read 호출당 ~54ms를 물렸다.

### 회귀 방지

| 테스트 | 검사 내용 |
|---|---|
| `test_write_guard_is_registered_for_write_and_edit_only` | 가드가 `Write\|Edit` 하나로만 등록됐는지 |
| `test_write_guard_judges_nothing_outside_an_active_run` | 전 Zone이 run-active 게이트 뒤에 있는지(구조 불변식) |
| `test_enforcement_prose_matches_the_restored_guard` | 문서·리마인더가 실제 강제와 일치하는지 |
| `test_write_hooks_are_post_tool_use_and_warn_only` | PostToolUse의 `Write\|Edit` 항목(redact-secrets)이 `--mode warn`인지 (PreToolUse의 `Write\|Edit` 가드는 별도 — Tier 1.1) |
| `test_guard_scripts_are_deleted` | `guard-read.py`·`guard-network.py` 파일 부재 |
| `test_hooks_json_has_no_read_or_bash_matcher` | `Read\|WebFetch`·`Bash` 매처 부재 |

---

## Tier 2 — 차단처럼 보이지만 차단력이 없는 것

### 2.1 `scripts/redact-secrets.py` (PostToolUse `Write|Edit`, `--mode warn`)

쓰기가 **끝난 뒤** 실행되므로 구조적으로 차단 불가. `warn` 모드는 매치를 **보고만** 하고 파일을 수정하지
않는다(파일 수정은 `strip` 모드 전용이며 훅에서 쓰지 않는다). 보고 경로는 공식 PostToolUse 출력 계약을 따른다 — 발견 시
`{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":…},"systemMessage":…}`를 stdout에 내고 **exit 0**
(v0.34.0; 이전의 exit 1은 PostToolUse에서 사용자에게만 보이는 non-blocking error라 모델에 전달되지 않았다 — exit 2만 stderr를 Claude에 보낸다). 탐지 대상: API 키·토큰, 패스워드, JDBC
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
| `REPO_AST_REQUIRE_JAVAPARSER` | `1` | v0.31.0부터 **no-op**(정규식 fallback 삭제로 항상 하드 실패). 차단이 아니라 품질 게이트 |
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

현재(v0.32.0+) 정상 상태는 `PreToolUse`에 `Skill|Task|Agent`(record-run-context)와 `Write|Edit`(guard-gate-artifacts), `PostToolUse`에 `detect_pipeline_state`와 `Write|Edit`(redact-secrets)가 보이는 것이다. `PreToolUse`에 `Read|WebFetch`나 `Bash` 매처가 보이면 v0.28.0 이하이므로 `/plugin update` 후 `/reload-plugins`가 필요하다. 훅 변경은 세션 시작 시점에 로드되므로 `/reload-plugins` 없이는 이전 버전 경로를 계속 쓴다.

---

## 참고 문서

- [Hooks reference](https://code.claude.com/docs/en/hooks) — PreToolUse/PostToolUse 차단 계약
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — 플러그인 `settings.json` 적용 범위
- [Sub-agents](https://code.claude.com/docs/en/sub-agents) — `tools`/`disallowedTools` 의미론
- [docs/GUIDE.md](./GUIDE.md) §2.5 — 훅 구성과 변경 이력
- [references/fallback-policy.md](../references/fallback-policy.md) — degrade 금지 정책(#2·#3·#20·#21)
