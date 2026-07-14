# Changelog

이 파일은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식을 따른다.
버전 관리는 [Semantic Versioning](https://semver.org/lang/ko/) 규칙을 따른다.

---

## [Unreleased]

---

## [0.25.0] - 2026-07-15

### Removed — PITest 기반 뮤테이션 기능 제거

- 선택 기능이던 `mutation-test` 스킬과 `mutation-analyst` 에이전트를 제거했다. 설정 인터뷰와 `HarnessRequest`/`HarnessConfig`의 관련 블록, 최종 `PipelineResult` 단계도 함께 제거했다.
- `build-test` MCP에서 관련 태스크·리포트 파서·게이트 카운터·빌드 능력 감지를 제거했다. 대상 프로젝트의 빌드 파일과 CI에 이미 추가된 관련 플러그인·태스크·환경 변수는 사용자 자산이므로 자동 삭제하지 않는다. 수동 정리가 필요하면 Gradle의 `info.solidsoft.pitest`와 `pitest { ... }`, Maven의 `org.pitest:pitest-maven`, CI의 `RUN_PITEST`·PIT 실행·리포트 업로드 단계만 제거하고 JaCoCo 설정은 유지한다.
- 배포 예제와 활성 문서에서 해당 설정 및 실행 경로를 제거했다. 과거 릴리스 기록은 변경하지 않는다.

### Changed — 최종 단계 번호와 산출물 재배치

- 커버리지 게이트(8단계) 다음의 시나리오 적합성 검증을 **9단계**, 조건부 자동 보정 루프를 **9.5단계**로 재배치했다.
- 중간 산출물은 `10_conformance.json` → `09_conformance.json`, `10b_conformance_repair.json` → `09b_conformance_repair.json`으로 변경했다. 기존 `_workspace/`의 옛 단계 산출물과 `_resume.json`은 새 실행에서 재사용하지 말고 새 계약으로 다시 생성해야 한다.
- 플러그인/마켓플레이스 버전을 `0.25.0`, MCP 패키지 버전을 `0.11.0`으로 올렸다. 배포 구성은 스킬 14종·에이전트 10종·MCP 서버 3종이다.

---

## [0.24.0] - 2026-07-15

### Added — 환경 세팅 전용 스킬 `setup-harness` 분리 (세팅과 실행의 분리)

- **`skills/setup-harness/`** 신규: 환경 세팅(**E1~E10** — Python 3.10+·MCP SDK·MCP 서버 등록·**E3b MCP 라이브 연결 검증**·JDK 21+·mvnw·JavaParser jar·JDT LS·실행 JDK↔Mockito)과 **상태줄 설치(S1)**를 단독으로 소유한다. `/test-autoevermation-harness-plugin:setup-harness`로 호출하며, 플러그인 설치 후 최초 1회 실행한다. **멱등** — 재실행 시 빠진 항목만 복구한다.
  - 상태줄은 기존 `hooks/statusline-autosetup.py`(SSOT)를 그대로 호출하므로 SessionStart 훅·`setup-statusline` 스킬과 consent 기록이 완전히 일치한다. 상태줄 실패는 `warnings`이며 세팅 실패가 아니다(선택 기능).
  - MCP `health`·`AskUserQuestion`은 서브에이전트에서 사용할 수 없으므로 이 스킬은 **메인 루프 전용**(`Task` 위임 금지)이다.

### Changed — `full-pipeline`·`configure-harness`는 세팅하지 않고 검증만 한다

- 두 스킬의 Phase E 실행 절차를 **E-verify 검증 게이트**로 대체했다. 시작 시 **부작용 없는 프로브**만 실행한다: `health`×3 실호출(E3b + 전이적으로 E1·E2·E3) · `java -version`≥21(E4) · shaded jar 존재(E5·E6) · `setup_jdtls.py --check-only`(E7) · 실행 JDK↔Mockito(E10).
- 프로브가 하나라도 실패하면 대화형·CI 동일하게 `status:"failed"`로 **파이프라인 미시작 하드 중단**하고 `"먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요"`를 안내한다. **자동 세팅·`setup-harness` 자동 위임·degrade는 모두 금지**다.
- **재사용·재개 경로 보강**: 기존 `00_config-harness.json` 재사용이나 durable resume으로 `configure-harness`를 건너뛰는 경우, 오케스트레이터가 **직접 E-verify 프로브를 실행**한 뒤 1단계로 진입한다 — MCP 등록은 **세션 단위**라 이전 실행의 통과가 이번 세션을 보장하지 않기 때문이다(프로브는 검증이지 세팅이 아니므로 위임 계약 위반이 아니다).
- **세팅 완료 증거는 파일이 아니라 프로브다.** `_workspace/`는 휘발성이고 "세팅 완료 리포트"는 stale 해질 수 있으며(JDK 제거·`mvn clean`·플러그인 업데이트로 venv 경로 변경), 무엇보다 세션 단위인 MCP 등록을 파일로 증명할 수 없다. 따라서 **새 산출물 파일을 만들지 않았고, 훅(`guard-gate-artifacts.py`·`record-run-context.py`)과 `hooks.json`은 변경이 없다.**
- `configure-harness`는 **0.5단계(E8·E9 프로파일 감지)·0.6단계(E11·E12 빌드 능력·캐시 프라이밍)·인터뷰·HarnessConfig 생성·도메인 스킬 스캐폴딩**을 그대로 유지한다. E11·E12는 인터뷰 결과 `mutation.enabled`에 의존하므로 세팅 단계로 앞당길 수 없다.
- SSOT 정렬: `references/environment-setup.md`에 **「역할 분담」·「E-verify 검증 프로브」** 절을 신설하고, `fallback-policy.md`(#1·#2·#3·#20)·`build-provisioning.md`·전 스킬·에이전트 문서의 "Phase E" 귀속을 `setup-harness`/E-verify로 정정했다. README·GUIDE·pipeline-flow(세팅 흐름 / 검증 게이트 2개 다이어그램으로 분리)를 최신화했다.
- 표준 라이브러리 회귀 테스트 `tests/test_setup_harness_split.py`를 추가했다(스킬 소유권·게이트 문자열·SSOT·프로브 플래그 실재성 계약).

---

## [0.23.0] - 2026-07-14

### Changed — PITest를 기본 비활성 선택 기능으로 전환

- `HarnessConfig.mutation.enabled`(기본 `false`)를 추가하고 full-pipeline 9단계가 비활성 상태에서 `PITEST_DISABLED`로 정상 `skipped`되도록 계약을 변경했다. 이 skip은 전체 파이프라인 상태를 낮추지 않는다.
- `detect_build_capabilities(..., require_pitest=false)`를 추가해 JaCoCo XML은 항상 필수로, PITest plugin/JUnit 어댑터/XML은 opt-in 시에만 필수로 판정한다. PIT 기본 HTML 출력과 MCP의 `mutations.xml` 소비 계약을 맞추기 위해 `pitestXml` 감지와 `PITEST_XML_DISABLED` remediation을 추가했다.
- `guard-gate-artifacts.py`는 정확한 비활성 skip 계약만 허용하고, 활성화 후 임의 skip은 계속 차단한다.
- Gradle/Maven 빌드 및 CI 예제, README/GUIDE/정책 문서를 선택형 계약으로 정렬했다. 표준 라이브러리 회귀 테스트를 추가했다.

---

## [0.22.2] - 2026-07-14

### Fixed — 상태줄 버전 표시가 플러그인 업데이트를 즉시 반영하지 못하는 문제

배경: `/plugin marketplace update`로 0.21.0→0.22.1 업데이트 직후에도 상태줄이
`#0.21.0`을 계속 표시했다. 원인 두 겹: ① wrapper의 `read_version`이 config에
설치 시점 고정된 `pluginRoot` 경로를 읽는데, Claude Code는 버전업 시 구 버전
캐시 디렉터리를 지우지 않고 새 디렉터리를 추가만 하므로 stale 경로가 계속
유효했다(SessionStart의 조용한 갱신은 다음 세션에야 돌아 업데이트 당일 세션은
내내 구버전 표시). ② `installed_plugins.json`은 v2 스키마
(`{"version":2,"plugins":{...}}`)인데 wrapper `plugin_present`와 autosetup
`resolve_install_path`가 최상위 키만 순회해 레지스트리 조회가 항상 미검출
(죽은 경로)이었다.

- `test-autoevermation-statusline.py`: `_registry_entries`/`registry_install_path`
  신설 — `read_version`이 **렌더 시점에 레지스트리의 현재 installPath를 최우선**
  으로 해석해, 업데이트 직후 세션 재시작 없이 새 버전을 표시한다(폴백:
  config pluginRoot → SCRIPT_DIR/..). `plugin_present`도 v2 스키마 정상 조회.
- `statusline-autosetup.py`: `resolve_install_path`가 v2 스키마의 `plugins` 중첩을
  처리(flat 구 스키마 병행 지원).
- 검증: 합성 픽스처 7케이스(레지스트리 우선/폴백/flat/v2·autosetup) + 실환경
  stale-config 재현(구버전 경로 config에서 새 버전 표시 확인).

---

## [0.22.1] - 2026-07-14

### Fixed — `guard-network.py` run-active 스코핑

배경: v0.22.0 배포 직후 이 플러그인 자신의 소스 저장소를 사람이 직접 수정·커밋·`git push`하는
개발 세션에서도 `guard-network.py`가 무조건 네트워크성 명령을 차단하는 것을 확인했다. 이 가드의
원래 위협 모델은 "파이프라인 실행 중 사람 감독 없는 서브에이전트가 데이터를 유출하거나 원격
상태를 건드리는 것"이지, "사람이 매 동작을 지시·승인하는 일반 개발 세션"이 아니다 — 후자에는
개입할 이유가 없고, 매번 `TEST_AUTOEVERMATION_HARNESS_NETWORK=on` 우회가 필요한 순수 마찰만
발생했다.

- `guard-network.py`에 `guard-gate-artifacts.py` Zone B/C와 동일한 **run-active 스코핑** 적용:
  `_workspace/.markers/run.json`(세션 일치, `record-run-context.py`가 기록)이 있을 때만 개입하고,
  없으면(=일반 Bash 세션) 네트워크성 명령을 무조건 허용한다. `TEST_AUTOEVERMATION_HARNESS_NETWORK=on`
  명시적 옵트인은 기존대로 항상 우선한다.
- 검증: 합성 stdin 8케이스(활성/비활성 세션 × git push·curl·일반 명령·stale 세션·env 오버라이드)
  전부 통과.

---

## [0.22.0] - 2026-07-13

### Added·Changed — 위임·산출물 물리 강제(enforcement) + forcing prose 복원

배경: v0.21.0 직후 실세션에서 full-pipeline이 **하네스를 통째로 우회**하는 회귀가 관측됐다
(자가보고: 0~7단계를 서브에이전트 위임 없이 인라인 수행, `_workspace` 산출물·`test_docs` 미기록,
사유는 일관되게 "직접 하는 편이 빠르다"). 원인은 두 겹: ① v0.21.0 SSOT 통합(토큰 절감)이
항상 로드되는 SKILL.md에서 **forcing prose까지 제거**(Phase E "TodoWrite로 전부 통과" 강제문,
5단계 생성 규칙 18개 등이 오케스트레이터가 Read하지 않는 references/로 이동), ② 훅 계층에
**위임·순서를 볼 수 있는 눈이 없음** — `Task`/`Agent` 매처 훅 부재로 "위임 안 함"은 감지 불가,
guard-gate-artifacts는 08/09 두 파일의 필드 불변식만 검사, **산출물을 아예 안 쓰는 우회
(bypass-by-omission)는 어떤 훅도 발화하지 않았다**. 교훈 아크: v0.18 "prose는 강제가 아님 →
필드 불변식 훅" → v0.21 SSOT가 forcing prose까지 제거 → **v0.22 "위임·순서도 필드 불변식처럼
물리 강제 + forcing prose 복원"**.

- **신규 `scripts/record-run-context.py`** (PreToolUse `Skill|Task|Agent` + PostToolUse
  `detect_pipeline_state`): full-pipeline 호출 시 `_workspace/.markers/run.json`(하네스 활성,
  세션 스코프) 기록 + `additionalContext`로 단계 계약 리마인더 주입, 파이프라인 subagent 스폰 시
  `spawn-<agent>.json`(위임의 물리 증거) 기록, 시나리오 미승인 상태(`04b_approval.json` 부재)의
  test-code-generator 스폰 deny(4.5 게이트를 스폰 시점에 차단), `detect_pipeline_state` 성공 시
  durable-resume 전제 마커 기록. 새 세션 시작 시 이전 세션 증거 자동 청소.
- **`scripts/guard-gate-artifacts.py` v2** (177→476행): 기존 08/09 필드 불변식(#21)에 더해 —
  Zone A) `_workspace` 단계 산출물 **provenance 강제**(producer 에이전트 자신 또는 spawn 마커
  보유 오케스트레이터만 기록 가능; durable-resume stub은 `source:"durable-scan"` + detect 마커
  전제) + 전 산출물 Edit 금지 + `00_config-harness.json` springProfile 필수 + **순서 게이트**
  (01|02→00, 05→04∧04b, 06→05, 08→06, 09→08; run-active 한정이라 단독 스킬 세션 오탐 없음) +
  08/09 **루프 증거 위조 검출**(iterations≥1 주장인데 coverage-closer/mutation-analyst 미스폰이면
  deny). Zone B) 하네스 활성 세션에서 오케스트레이터의 `src/test/java` 기록 deny(허용:
  test-code-generator·coverage-closer·mutation-analyst·test-fixer; 오케스트레이터 Edit는
  spawn-test-fixer 마커 보유 시 patch-apply로 허용; `04b` 승인 이전 기록은 누구든 deny).
  Zone C) `test_docs/scenarios|refactoring` 문서의 선행 산출물 게이트. 비파이프라인 세션은
  Zone B/C 완전 비활성(일반 개발 오탐 0). 인프라 fail-open·판정 fail-closed 유지.
- **full-pipeline SKILL.md forcing prose 복원(v0.20.1 수준 재인라인)**: 상단에 **단계 계약 표**
  (단계→필수 수행 주체→산출물, 훅 강제 명시) 신설, Phase E 대상 항목·세팅 방식·검증 후 체크·게이트
  4개 절 + configure-harness "TodoWrite로 전부 통과" 강제문 복원(오케스트레이터 인라인 수행·
  AskUserQuestion 직접 대체는 계약 위반 명시, E3b는 "응답 수신"이 아닌 health 3종 필드 확인),
  5단계 생성 규칙 18개 재인라인(정본 references/test-code-invariants.md 병기; **소유권 반전
  "오케스트레이터 재Write 금지"는 유지** — Zone B 훅과 맞물리는 설계), 7단계 생성 원칙·무진전
  중단 규칙 전문 복원, 8/9단계 #21 무효 술어 재인라인, resume stub 유효성(훅 강제) 1줄,
  실패 처리 표에 8/9 술어 복원 + **위임 우회(훅 deny 수신) 행** 추가.
- **orchestration-detail.md §2-1**: 모든 durable-resume stub에 `source:"durable-scan"` 필수 명시
  (guard의 stub 판별 계약과 정합).
- **hooks/hooks.json**: record-run-context 2개 엔트리 배선. **`scripts/dev/probe-hook-stdin.py`**
  신규(훅 stdin 계약 드리프트 재검용 — 이번에 `agent_type`/`agent_id` 서브에이전트 채움·`Agent`
  스폰 도구명·`tool_input.skill` 키·세션 동일성·MCP 풀네임 매칭을 headless 라이브 세션으로 실증).
- 검증: 합성 stdin 단위 43케이스 전부 통과(각 Zone deny/allow 전 행 + malformed/Windows 경로/
  stale 마커/오탐 0 확인) + headless 라이브 E2E(스킬 호출→run.json 생성, 무위임 04 Write deny,
  승인 전 테스트 Write deny, 일반 파일·오케스트레이터 산출물 allow).

---

## [0.21.0] - 2026-07-12

### Fixed — 전수 감사(오케스트레이션 신뢰성): 도구명 해석·가드 fail-open·핸드오프 계약 정합

배경: 에이전트·스킬 전수 감사(병렬 판독 + 공식문서 팩트체크 + 라이브 세션 실증)에서, 프롬프트가
약속한 계약과 런타임 실제 동작이 어긋나는 지점들을 확인했다. 세 가지가 치명적이었다: ① 플러그인
MCP 도구는 런타임에 `mcp__plugin_<plugin>_<server>__<tool>` 스코프드 네임으로만 노출되는데
(공식 plugins-reference; 하네스 에이전트 실측 프로브로 재확인) 에이전트 frontmatter `tools:`가
전부 축약명(`mcp__repo-ast__*`)이라 **allowlist가 아무 MCP 도구도 부여하지 못했다**. ② PreToolUse
훅의 거부는 `hookSpecificOutput.permissionDecision` 중첩 스키마만 유효한데 가드 3종이 top-level
형식을 써서 **전부 fail-open**이었다(네트워크 OFF인데 WebFetch가 통과하는 것을 라이브로 실증 —
v0.18.0 "물리 강제" 게이트 차단 포함 무효 상태였음). ③ 생산자가 만들지 않는 필드를 소비자가
기대하는 핸드오프 불일치 다수(모델이 그 자리에서 지어내게 만드는 1급 할루시네이션 유발원).

- **P0-1 MCP 도구명 스코프드 정합**: 11개 에이전트 frontmatter + 본문 리터럴 6곳
  (full-pipeline·measure-coverage·mutation-test·orchestration-detail·GUIDE)을 스코프드 네임으로 교체.
- **P0-2 가드 훅 스키마 수정 + 과차단 정밀화**(`scripts/guard-network.py`·`guard-read.py`·
  `guard-gate-artifacts.py`): deny/allow를 `hookSpecificOutput` 중첩 형식으로 교체(20케이스 파이프
  단위검증 통과). 켜지는 순간 과차단할 패턴 2건 정밀화 — `\bhost\b` 단어 매칭 제거(JDBC·datasource
  인자 오차단), bare `https?://` 매칭을 fetch 동사 결합으로 대체(git clone/fetch/pull/push·urlopen 등),
  guard-read의 build/target 세그먼트를 빌드 산출 루트로 앵커(`src/**/build` 자바 패키지 오차단 방지).
- **P0-3 서브에이전트 질문 라우팅 정정**: AskUserQuestion은 서브에이전트에서 사용 불가(공식 명시)
  — test-runner·spec-reviewer의 직접 호출 지시를 "신호 반환 → 오케스트레이터(스킬)가 질문" 패턴으로
  교정하고, test-runner의 "빈 스코프=전체 실행" 자기모순을 #8 정합으로 수정.
- **P0-4 핸드오프 계약 정밀화 6건**: (a) `ConformanceResult.unmet`(string[])에서 객체 필드를 꺼낸다는
  서술 2곳을 "scenarioResults 조인" 규약으로 정정 (b) scenario `target`을 `FQCN#method` 형식으로 명시
  (5·10단계 게이트 전제) (c) `AstAnalysisResult.testTargets[]`에 `file` 경로 패스스루 추가 + 7단계
  `relatedSources`를 astResult 기반으로 정정(존재하지 않는 sourceResult 경로 참조 제거)
  (d) `TestGenResult.files[].testClass` 필수 승격(6단계 스코프 입력) (e) verify-scenarios의 메서드
  단위 판정 추론 규칙 명문화(run-tests는 집계+failed[]만 반환) (f) full-pipeline 전처리의
  `projectRoot=cwd`·auto-detect 기본값을 #13(자동 채움 금지)과 정합.
- **P0-5 `coverage_gate`에 `require_pitest` 파라미터 추가**(`mcp/build_test_server.py`): 8단계
  (뮤테이션 이전)에서 PITest 리포트 부재가 무조건 `status:"partial"`을 만들던 구조 결합 해제
  (기본 False — 부재 시 MUTATION 카운터만 생략, 리포트가 있으면 항상 평가; 3케이스 단위검증 통과).

### Changed — 중복 통합·토큰 절감·문구 신선도 (P1)

- **SSOT 통합**: MCP-필수 상용구 ×11스킬 → fallback-policy #20 포인터 1줄로; 신규
  `references/test-code-invariants.md`(생성 테스트 불변식 SSOT — 금지 패턴·scenarioRef 보존·BDD/stub·
  프로파일 관용구·스타일)를 만들고 test-code-generator·test-fixer·coverage-closer·mutation-analyst의
  재서술 블록을 포인터로 교체; 신규 `references/agent-result-envelope.md`(공통 결과 봉투 SSOT)로
  에이전트 공통 필드 표 8곳 교체; full-pipeline의 Phase E 절차 재서술을 configure-harness 위임+산출물
  확인으로 축약, #21 블록 ×5·무진전 규칙 반복을 포인터화; 5·7단계 Task 프롬프트의 생성 규칙 재서술을
  에이전트 정의 참조로 축약(서브에이전트 시스템 프롬프트와 중복이었음).
- **흐름 정밀화**: 4단계 입력을 사용 필드 서브셋(testTargets/testSeams·collaborators/acceptanceCriteria
  등)만 전달하도록 슬리밍; 5단계 파일 기록 소유권을 에이전트로 단일화(오케스트레이터 이중 Write 제거,
  `files[].content` 선택화); `seamRefs`=testSeams 문자열 verbatim 정의; mutation-analyst 입력에
  `totalMutants` 추가(분모 미제공 수식 해소); 8·9단계에 `junitPolicy`/`stylePolicy` 스레딩;
  configure-harness CI 판별 4번째 조건을 실존 경로(HarnessConfig 재사용)로 교체; E1/E2 프로비저닝
  명령을 `launch.cjs --ensure-only` 단일 진입점으로 통일; `detect_pipeline_state` 미노출=구버전 설치
  신호(#20 준용 remediation) 명시; `redact-secrets.py`가 PostToolUse 훅 envelope에서 기록 페이로드만
  추출해 스캔(파일경로:라인 리포트, 4케이스 단위검증 통과); methodCalls 공백의 원인 구분을 repo-ast
  `degraded` 플래그로 명문화(생성기·적합성 검증기); JDT LS 문구 정밀화 — 정책(#3 필수)은 유지하되
  에이전트가 직접 LSP를 호출한다는 거짓 능력 서술 제거, refactor-advisor는 #19(보조 게이트) 정합으로
  경고 후 진행, repo-ast `nextActions`의 미구현 JDT 제안 문구 교정.
- **신선도**: GUIDE의 `.mcp.json` 기동 방식(python3 직접→`launch.cjs`), fallback 정책 개수 하드코딩
  제거(19→문서 정본), `maxRepairRetries` 기본 2→3(#12 무진전 "3회 연속"과 정렬 — full-pipeline·GUIDE),
  README 제거/재설정 절을 GUIDE §4.5–4.6 링크로 축약(사본 drift 제거).

### Fixed — 예제·문서 일관성 (P2)

- 모순 예제 교정(모델이 그대로 모방하는 할루시네이션 원천): mutation-analyst 예제 수치 정합
  (0.83 vs 17/20=0.85 → totalMutants 20 기준 0.90으로 일관), source-code-analyzer 예제의
  `lspAvailable:false`(자체 규칙상 즉사 입력)→true·`springBootVersion 4.1.0`(미검증)→3.4.5,
  analyze-source 출력 예시를 스키마와 필드 단위 정합(collaborators fqcn/role/injectionType/mockable 등),
  generate-scenarios 예제에 `mockTargets`/`sliceAnnotation` 보강, refactor-advisory INDEX 템플릿의
  유령 버전 `v0.9.0`→plugin.json 동적 참조 플레이스홀더, `<pluginRoot>` 리터럴→`${CLAUDE_PLUGIN_ROOT}`.
- spec-doc 서버: `SPEC_DOC_REDACT_EMAIL=off`로 EMAIL 마스킹만 개별 해제 가능(스펙 예시 이메일을
  테스트 fixture로 써야 하는 경우), allowlist를 경로 컴포넌트 부분일치로 완화("documentation"도 "doc"
  항목으로 허용), `index_docs`가 호출마다 인덱스를 전체 교체함을 docstring에 명시(배치 호출 시 유실
  방지); repo-ast `resolve_symbol`의 부분 스코프(테스트타깃만 필터링) docstring 명시.

---

## [0.20.1] - 2026-07-10

### Fixed — durable resume의 test 출처(provenance) 구분: 손수 짠 기존 테스트를 "생성 완료"로 오인하지 않음

배경: v0.20.0 `detect_pipeline_state`는 `src/test/java`에 `*Test*.java`가 있으면 **파일명만 보고**
`hasTests=true`로 판정해 그 테스트를 "5단계(테스트 생성) 완료"로 간주했다. 문제는 그 테스트가 *이
하네스가 생성한 것*인지 *원래 프로젝트에 손으로 짠 것*인지 구분하지 않았다는 점이다. 결과적으로
기존 손수 짠 테스트만 있는(하네스를 처음 돌리는) 프로젝트에서도 1~5단계(스펙·AST·소스 분석 →
시나리오 설계 → 테스트 생성)를 건너뛰고 6단계(실행)부터 시작해, **정작 커버리지 갭을 메우는 새
테스트를 전혀 생성하지 않는** 오작동이 있었다.

- **provenance 게이트 추가**(`mcp/build_test_server.py` `detect_pipeline_state`): 하네스가 생성한
  테스트는 `test_docs/`(시나리오 문서·`INDEX.md`)로 증명된다. 이 흔적이 없으면 기존 테스트는 FOREIGN
  으로 판정한다 — 새 필드 `harnessProvenance`(bool)·`foreignTestsPresent`(bool)를 반환하고,
  foreign 테스트는 `highestCompletedStage`를 5단계로 올리지 않으며 `recommendedEntryStage`를 0(초기
  실행)으로 둔다. `resumable`은 "하네스 파이프라인이 중간 상태를 남겼는가"를 뜻하므로 foreign-only는
  `false`다.
- **Phase 0 분기 추가**(`skills/full-pipeline/SKILL.md` · `references/orchestration-detail.md` §2-1·§3):
  `foreignTestsPresent:true`(손수 짠 테스트만)면 0단계부터 **정식으로** 시나리오 설계·테스트 생성을
  진행하되, 감지된 `testFiles[]`를 5단계 generate-tests·8단계 coverage-closer의 `existingTestPaths`로
  전달해 **기존 테스트를 덮어쓰지 않고 커버리지 갭만 공존 보완**한다. foreign 테스트에는 `05` stub을
  복원하지 않는다.
- 문서 반영: `README.md`·`docs/GUIDE.md`(§3.5·§5.6 FAQ)에 하네스 생성 vs 손수 짠 테스트 구분을 명시.

---

## [0.20.0] - 2026-07-09

### Added — 영속 증거 기반 상태 복원(durable resume): 테스트가 이미 있어도 알맞은 단계부터 재개

배경: `full-pipeline`의 재개 로직은 지금까지 **오직 `_workspace/` 디렉터리 존재 여부**로만
분기했다(`skills/full-pipeline/SKILL.md` Phase 0). 그런데 `_workspace/`는 `.gitignore` 대상
휘발성 산출물이라, fresh clone·`git checkout`·새 세션·workspace 로테이션 후에는 **생성 테스트
(`src/test/java`)·승인 시나리오(`test_docs/scenarios/`)·JaCoCo/JUnit/PITest 리포트가 그대로
남아 있어도** `_workspace/`만 사라져 Phase 0가 "없음 → 초기 실행(0단계부터 전체)"으로 오분류했다.
결과적으로 "이미 테스트가 있는 상태에서 보완/수정"을 요청해도 설정·분석·시나리오 재설계·테스트
재생성을 전부 다시 돌리며(매 파일 overwrite 확인), 알맞은 중간 단계부터 재개하지 못했다.

- **`detect_pipeline_state` MCP 도구 추가**(`mcp/build_test_server.py`): 영속 증거를 **결정적으로**
  스캔해 완료 단계를 물리 판정한다(LLM 눈대중 아님). `src/test/java`·`test_docs/scenarios`(approval
  카운트)·`test_docs/refactoring`·JUnit/JaCoCo/PITest 리포트(기존 파서 재사용)를 읽어
  `highestCompletedStage`·`recommendedEntryStage`·`resumable`·증거 경로를 반환한다. 파서 부재/에러는
  fail-safe(null)로 처리해 감지가 파이프라인을 깨지 않는다.
- **Phase 0 재개 로직 재작성**(`skills/full-pipeline/SKILL.md`): 2분기(`_workspace/` 유무)를
  3신호 해석으로 교체. `_workspace/` 부재·불완전 시 `detect_pipeline_state`로 판정 → 최소 stub
  산출물 재구성 + `_workspace/_resume.json` 기록 후 **재진입 단계 확정**(대화형=`AskUserQuestion`으로
  6/8/9/4 선택 · CI=`recommendedEntryStage`, 기본 6→8→9→10 재생성 없이 보정). 규약 정본:
  `references/orchestration-detail.md` §2-1(영속 증거→stub 복원 표) + §3(durable 매트릭스 행).
- **상태줄 재개 표시**(`scripts/test-autoevermation-statusline.py`): `_workspace/_resume.json`이
  있으면 표시 단계를 재진입 지점으로 **clamp**하고 `↩ resumed @ <단계>`로 표기 —
  재개 지점보다 뒤의 stale 산출물이 있어도 진행률을 과대표시하지 않는다.
  `pipeline_result.json`이 생기면 `100% | done`이 우선한다.

---

## [0.19.0] - 2026-07-08

### Added — 상태줄 자동 설치·자동 제거(수동 스킬 호출 불필요)

배경: 상태줄(`[Test-AutoEverMation#x.y.z] … | stage …`)은 지금까지 사용자가 직접
`setup-statusline` 스킬을 불러야 설치되고, 제거도 수동이었다. 게다가 Claude Code 플러그인은
**install/uninstall 라이프사이클 훅이 없어**(공식 문서 확인) `/plugin uninstall`이 전역
`settings.json`의 `statusLine` 수정을 되돌리지 못한다 → 제거 후에도 상태줄 줄이 남았다.
또한 플러그인 settings로는 main statusLine을 설정할 수 없어(공식: `agent`/`subagentStatusLine`만
적용) OMC HUD 등이 상태줄 슬롯을 되가져가면 TAM 줄이 사라지곤 했다.

- **전역 자가 완결 런처 도입**: `${CLAUDE_CONFIG_DIR:-~/.claude}/`에 wrapper(`test-autoevermation-statusline.py`)와
  독립 런처(`test-autoevermation-statusline-launch.cjs`)를 설치하고 `statusLine.command`가 런처를
  가리키게 한다. 플러그인 캐시가 삭제돼도 이 전역 사본은 살아남는다.
- **자동 제거(self-heal)**: 전역 wrapper가 렌더마다 플러그인 설치 여부(installPath 존재 +
  `installed_plugins.json` 등록)를 확인해, uninstall을 감지하면 1회 한정으로 `settings.json`을
  원래 상태줄(delegate)로 원복하고 전역 사본을 정리한다. uninstall 후 첫 상태줄 렌더에서 반영.
- **자동 설치(SessionStart 훅 `statusline-autosetup.py`)**: consent=granted면 매 세션 시작에
  조용히·멱등하게 전역 파일을 갱신하고 statusLine 슬롯을 재점유한다(OMC 되가져감 복구 포함,
  이중 래핑 금지). 최초 설치 직후 consent 미결정이면 `additionalContext`로 어시스턴트에게
  1회 확인(AskUserQuestion)을 요청한다. 기존 상태줄(OMC HUD 등)은 delegate로 보존.
- **kill switch**: 환경변수 `TAM_STATUSLINE_AUTO=0`으로 자동 설치를 비활성화(CI 권장).
- `setup-statusline` 스킬은 이제 `statusline-autosetup.py`(`--install`/`--uninstall`)에 위임한다.
- 표시 범위: 모든 세션(파이프라인 없는 프로젝트에선 버전만 표시).

---

## [0.18.0] - 2026-07-06

### Added — 8·9단계 게이트 스킵 방지 (오케스트레이션 오류 차단)

배경: 실제 실행에서 오케스트레이터가 8단계 커버리지 게이트 미달을 확인하고도 coverage-closer를
호출하지 않고 "RA advisory 대상 — 구조적 커버리지 한계"라는 자체 판단으로 10단계로 건너뛴 사건.
계약상 미달 분기는 coverage-closer 호출 단 하나이고 advisory는 4단계 입력 필터링에만 관여하지만
(refactor-advisory), 이를 기계적으로 강제할 장치(Stage 5 `targetCallCheck`류)가 8·9단계에 없었다.

- **fallback-policy #21 신설**: RA advisory 비면제 원칙 + 게이트 산출물 무효 조건 —
  `gatePassed:false`∧(`iterations<1`∨`remainingGaps` 빈 배열) / `thresholdMet:false`∧
  (`iterations<1`∨`survivingMutants` 빈 배열)이면 게이트 미수행 산출물로 무효, 해당 단계 재실행 의무.
  "구조적 커버 불가" 판단은 coverage-closer/mutation-analyst가 루프 수행 후
  `remainingGaps[].reason`/`survivingMutants[]`로만 성립하고, 스코프 제외는
  `HarnessConfig.coverage.excludes`(사용자 승인)로만 — JaCoCo `classDirectories` excludes·
  PIT `excludedClasses`와 동일한 선언적 제외 모델.
- **`scripts/guard-gate-artifacts.py` 훅 신설** (PreToolUse `Write|Edit`): 무효
  `08_coverage_result.json`/`09_mutation_result.json` 기록을 기계적으로 deny(사건 시나리오
  재현 케이스 포함 12케이스 결정 테이블 검증). 게이트 산출물의 Edit 부분 수정 금지(Write 전체 기록),
  `status:"failed"` 도구 고장 경로는 허용, 인프라 오류 시 fail-open.
- **계약 명문화**: full-pipeline 8·9단계(스킵 금지+무효 조건+집계 유효성 교차검증), measure-coverage·
  mutation-test 절차, refactor-advisory 공통 규칙 4(하류 효과 한계), orchestration-detail §6,
  pipeline-flow §1, GUIDE §3.2 동기화.

---

## [0.17.0] - 2026-07-06

### Added — 시나리오 target 호출 게이트 + 적합성 자동 보정 루프

배경: 통과하지만 잘못된 메서드를 호출하는 테스트(예: 시나리오 target `recordMoResult` 대신 유사명
`recordMtResult` 호출 — MO/MT 혼동)가 5→6→7→8→9단계를 전부 통과하고 10단계에서 발견돼도
보고로만 끝나는 설계 결함이 확인됨. 생성 게이트(사전 차단)와 자동 보정 루프(사후 교정)를 추가.

- **repo-ast `invokedMethods`/`methodCalls`**: JavaParser CLI(`AstCli`)가 각 메서드 본문이 호출하는
  메서드 **단순명 목록**(`invokedMethods`)을 추출(인자·본문은 계속 미출력 — 보안 계약 유지).
  `repo_ast_server.py`가 각 testTarget에 `methodCalls`(메서드명→호출 목록 맵)로 노출. 정규식 폴백은 빈 목록.
- **5단계 target 호출 자가 검증 게이트** (`test-code-generator`, `generate-tests`): 파일 기록 후
  `parse_java_file`의 `methodCalls`로 각 `scNNN_` 메서드가 시나리오 `target` 메서드를 실제 호출하는지
  대조(unit=기계 대조 / slice=when·given 문자열 대조). `files[].targetCallCheck`
  (`matched`/`manual-verified`/`mismatch`) 필수화 — 오케스트레이터는 필드 누락·mismatch 파일을 Write하지 않고
  `SCENARIO_TARGET_MISMATCH`로 보고.
- **10단계 기계 판정 강화** (`scenario-conformance-verifier`, `verify-scenarios`): target 호출을
  `methodCalls` 기계 대조로 판정(LLM 판단 아님), `scenarioResults[].nonconformanceClass`
  (`WRONG_TARGET_CALL`/`THEN_GAP`/`GIVEN_MISMATCH`/`MAPPING_MISSING`) 추가 — 10.5단계 라우팅 힌트.
- **10.5단계 적합성 자동 보정 루프** (`full-pipeline`): `unmet` 존재 시 대화형·CI 동일하게 자동 보정 —
  unsatisfied→`test-fixer` **모드 B**(신규 입력 `nonconformantItems[]`, `rootCauseClass`에
  `SCENARIO_NONCONFORMANT` 추가, 최소 diff·단언 강화만 허용) / missing→`test-code-generator` 부분 재생성 →
  6단계 재실행 → 10단계 재검증. **최대 3라운드, 동일 unmet 집합 즉시 무진전 중단**(#12의 명시적 예외 —
  적합성 판정은 일부 LLM 판단이라 진동 위험). 라운드 로그 `_workspace/10b_conformance_repair.json`,
  `PipelineResult.stages.conformanceRepair` 추가.

### Changed
- **fallback-policy #16 재작성**: "보고 후 종료(대화형만 선택적 재실행)" → "10.5 자동 보정 루프
  (대화형·CI 동일) → 소진 후 잔여만 질문/partial". `verify-scenarios`의 `AskUserQuestion`은
  단독 호출·루프 소진 후로 한정.
- `docs/pipeline-flow.md`(§1·§5 다이어그램, §7 매핑표)·`orchestration-detail.md`(부분 재실행 매트릭스,
  `_workspace` 트리, 에러 표)·`scenario-docs.md` §4·README·GUIDE 동기화.

---

## [0.16.0] - 2026-07-06

### Changed — **Breaking: MCP 필수화 (silent degrade 전면 제거)**
- **JavaParser 백엔드 필수화**: `.mcp.json`이 repo-ast에 `REPO_AST_REQUIRE_JAVAPARSER=1`을 기본 설정 —
  jar/JDK 미가용 시 정규식 fallback(`degraded:true`)으로 진행하지 않고 `status:"failed"`(`JAVAPARSER_REQUIRED`)로
  하드 실패한다(정규식 경로는 서버 스크립트 단독 사용 시에만 코드 기본값으로 잔존). jar는 gitignore된 빌드 산출물이므로
  Phase E·E6가 동봉 Maven wrapper로 자동 빌드(`cd mcp/javaparser-cli && ./mvnw -q -DskipTests package`)하고,
  실패 시 하드 중단한다. fallback-policy #2 개정.
- **JDT LS 필수화(E7)**: optional·AST-only degrade 제거 — Phase E·E7이 `scripts/setup_jdtls.py`로 자동
  설치(PATH → brew(macOS) → eclipse.org milestone tarball → `${CLAUDE_PLUGIN_DATA}/jdtls`)하고, 실패 시 하드 중단.
  `lspAvailable:false` 상태로 파이프라인 진입 금지. fallback-policy #3 개정.
- **JDK 21+ 필수(E4)**: jar 빌드(17+)와 JDT LS 구동(21+, Eclipse JDT LS 공식 요구) 요건을 "JDK 21+" 단일
  메시지로 통합. 대상 프로젝트의 테스트 실행 JDK(E10, Mockito/ByteBuddy 호환)와는 별개.
- **"무설치(zero-install)" 문구 철회**: README·GUIDE·DEPENDENCIES 전제조건을 정직화 — Node.js(동봉),
  **JDK 21+(필수)**, Maven(선택 — mvnw 동봉), 첫 세팅 1회 네트워크(uv Python·Maven 의존성·mvnw 배포판·JDT LS
  tarball). 오프라인 대안: 사전 빌드 jar를 `REPO_AST_JAVAPARSER_JAR`로 지정 + jdtls 사전 설치.
- 스킬 11종(analyze-ast·analyze-source·ingest-specs·run-tests·generate-scenarios·generate-tests·repair-tests·
  measure-coverage·mutation-test·refactor-advisory·verify-scenarios)에 "MCP 필수(대체 금지)" 규칙 명시,
  에이전트 3종(ast-structure-analyzer·source-code-analyzer·refactor-advisor)의 degrade 서술을 하드 중단으로 개정.

### Added
- **MCP 서버 3종에 `health` 도구 신설**: 무부작용 연결·백엔드 상태 프로브 — repo-ast는
  `{pluginVersion, javaparser:{jarFound, jarPath, javaOk, requireJavaparser}, allowRoot}`, spec-doc은
  redact/allowlist, build-test는 networkAllowed를 함께 반환한다.
- **Phase E 신규 게이트 E3b(MCP 라이브 연결 검증)**: 파이프라인 시작 전 메인 루프가 `health` 3종을 **실제
  호출**해 세션 연결을 검증 — E3의 import 검사로는 잡히지 않던 플러그인 MCP 등록 실패를 차단. 실패 시 하드
  중단 + remediation(플러그인 활성화 확인 → `launch.cjs --ensure-only` → `/reload-plugins`/재시작).
  fallback-policy **#20 신설**(파이프라인 도중 MCP 도구 호출 실패 포함, Grep/Read 대체 금지).
- **`scripts/setup_jdtls.py`**(stdlib·크로스플랫폼·멱등)와 **`mcp/jdtls-launcher.cjs`**(PATH →
  `${CLAUDE_PLUGIN_DATA}/jdtls` 순 해석 spawn 래퍼) 추가, `.lsp.json`을 node 래퍼 경유로 전환.
- **`mcp/javaparser-cli`에 Maven wrapper(`mvnw`/`mvnw.cmd`) 동봉** — 시스템 Maven 전제 제거.
- **제거(uninstall)·재설정(reset) 가이드**: 루트 `README.md`·플러그인 `README.md`·`docs/GUIDE.md`(§4.5·§4.6)에
  플러그인 제거(`/plugin uninstall`)·비활성화(`/plugin disable`/`enable`)·마켓플레이스 해제
  (`/plugin marketplace remove` — 소속 플러그인 동반 제거 경고 포함)·로컬 설치본(symlink/복사) 삭제 절차를 추가.
  재설정은 3가지 시나리오로 구분: ① 일반 업데이트(`/plugin marketplace update` + `/reload-plugins`),
  ② 설치 상태 손상 시 플러그인 캐시 초기화(`rm -rf ~/.claude/plugins/cache`, 공식 트러블슈팅 절차),
  ③ 하네스 실행 상태 재설정(대상 프로젝트 `_workspace/` 삭제 — 다음 실행이 처음부터 시작되며,
  사람이 읽는 영속 산출물인 `test_docs/`는 보존). GUIDE §9 트러블슈팅 표에 캐시 손상 증상 행 추가.
  근거: [Discover and install plugins](https://code.claude.com/docs/en/discover-plugins)(2026-07-06 재검증).

---

## [0.15.0] - 2026-07-05

### Added
- **Windows 네이티브 지원 — OS 의존 제거.** MCP·훅 진입점을 POSIX `sh`(run-server.sh)에서 **크로스플랫폼 Node 런처 `mcp/launch.cjs`**로 교체. 공식 문서 근거: 훅/플러그인 exec form(`command`+`args`)은 셸을 거치지 않고 실행 파일을 직접 spawn하며 "node + 스크립트 경로 패턴은 node.exe가 실제 바이너리이므로 전 플랫폼 동작"(hooks 공식 문서); Windows에서 셸 형식은 Git Bash 유무에 따라 PowerShell로 갈라져 신뢰 불가. 런처 모드: `<server.py>`(서버 기동)·`--ensure-only`(SessionStart)·`script <py>`(훅/statusline, fail-open). Python 해석: 핀 → Windows `py -3`/`python`/`python3`, POSIX `python3`→3.13…3.10 (sys.executable로 정규화 — Windows Store 가짜 python.exe는 버전 체크에서 걸러짐). 미존재 시 uv 자동 설치: POSIX `install.sh`(curl|wget) / **Windows 공식 `install.ps1`**(`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, astral 공식 문서). mkdir 락 직렬화·수동 폴백 안내(exit 2)는 run-server.sh와 패리티 + 강제 종료로 고아가 된 락의 시효(10분) 파기와 설치 구간 한정 시그널 핸들러 스코프를 추가(리뷰어 lane 지적 반영 — run-server.sh에는 없던 견고성). `.mcp.json` 3서버와 hooks.json 4훅 전부 exec form(node)으로 전환(`python3` 하드코드 제거).
- **build-test Windows 빌드 래퍼 지원**: `detect_build_tool`이 `gradlew.bat`/`mvnw.cmd`(공식 래퍼 산출물)도 인식, `_build_test_command`가 Windows에서 배치 래퍼를 `cmd.exe /s /c "…"` 문자열로 실행 — CreateProcess는 배치 직접 spawn 불가하고, `/c` 단독은 따옴표 제거 규칙(`cmd /?`)으로 공백 경로(`C:\Users\John Doe\…`) 래퍼를 깨뜨리므로 `/s` + tail 전체 재인용을 사용(리뷰어 lane 지적 반영). 이에 필수인 `test_pattern` 화이트리스트 검증(`[A-Za-z0-9_.$#*,!\[\]]+` — `!`/`[]`는 Surefire 제외·파라미터화 선택자) 추가 — cmd.exe 메타문자 유입(BatBadBut류) 차단, 전 OS 공통 방어.
- **guard-network Windows 도구 차단**: `Invoke-WebRequest`/`Invoke-RestMethod`/`iwr`/`irm`/`certutil -urlcache`/`bitsadmin`/`Start-BitsTransfer`/`Net.WebClient` 패턴 추가(curl.exe/wget.exe는 기존 패턴이 매칭).

### Changed
- statusline 래퍼의 delegate 실행을 `/bin/sh` 하드코드에서 OS 분기(`COMSPEC`/`cmd.exe /c` ↔ `/bin/sh -c`)로. `setup-statusline`의 statusLine 커맨드 정본을 `node launch.cjs script …` 형식으로(기존 python3 형식은 POSIX에서 유효 — 경로 갱신 시에만 교체).
- README(사전 요구사항: Node.js 행 신설, Windows 네이티브 지원 명시)·GUIDE(§4.2, 트러블슈팅)·DEPENDENCIES·environment-setup(E1 전 OS)·configure-harness·full-pipeline의 진입점 서술을 launch.cjs 기준으로 동기화. POSIX 전용 `run-server.sh`는 수동 폴백으로 유지.
- 참고: `bootstrap.py`는 변경 없음 — venv 경로 `Scripts/python.exe`(nt) 분기와 fcntl 불가 시 무락 진행(fail-open)이 이미 Windows 호환이었다(이번 전환으로 해당 경로가 실사용됨).

---

## [0.14.1] - 2026-07-04

### Fixed
- **spec-doc `extract_acceptance_criteria`가 실사용 마크다운 형식을 놓치던 결함 수정** (런타임 스모크 테스트로 발견 — MCP 3서버 실기동 `tools/call` 전수 호출 중 유일하게 빈 결과를 반환한 도구). 기존 구현은 `Scenario:`/`시나리오:` **헤더가 있는 블록만** 매칭해, ① 헤더 없는 Given/When/Then 연속 줄, ② 마크다운 불릿(`- Given ...`), ③ 한 줄 인라인(`Given X, When Y, Then Z`)을 전부 0건으로 반환했다. 정규화 전처리(불릿/번호 프리픽스 제거 + 인라인 GWT 줄 분리)와 헤더리스 블록 2차 패스(키워드 줄 2개 이상, `\b` 경계 추가로 "Andrea" 류 오탐 방지, 헤더 블록과 span 중복 제거)를 추가했다. 헤더 없는 블록의 title은 when(없으면 then)에서 유도.
- **금지 규칙 키워드 보강**: `해서는 안`만 있고 `되어서는 안`/`돼서는 안`이 없어 "음수가 되어서는 안 된다" 류 금지 문장을 놓치던 것을 rule 추출·prohibition 분류 양쪽에 추가. RULE 문장 앞 마크다운 불릿 제거.
- 검증: 실서버 stdio 경유 재호출로 3형식(인라인 불릿/클래식 헤더/규칙 문장) 모두 추출 확인, 클래식 형식 회귀 통과. 그 외 런타임 스모크는 전부 정상 — MCP 3서버 initialize/tools-list(17종 일치), build-test 8개 도구 픽스처 실호출(JUnit XML 실패 분류·JaCoCo uncovered·coverage_gate 카운터 판정·spring profile interviewRequired·build capabilities 4종 감지), repo-ast 4개 도구(JavaParser jar 정밀 경로, degraded=false), 훅 3종(guard-network deny/allow, guard-read deny/allow, redact-secrets 경고+비0 exit), statusline 진행률(21% 계산 정확), record-timing 스키마 일치.

---

## [0.14.0] - 2026-07-04

### Fixed
- **전수 계약 감사(스킬 14·에이전트 11·MCP 3종) — "미전달·미연결" 배선 공백 일괄 수정.** v0.13.2의 7단계 self-healing 배선 수정과 동일 클래스의 공백을 파이프라인 전 구간에서 감사(0–5단계/6–10단계/MCP 계층 3축)해 수정했다.
  - **0–5단계 계약 정렬**: `testScope`가 scenario-generator에 착지 필드 없이 전달되던 3자 불일치 해소(에이전트 입력·스킬 전달 추가). scenario-generator 출력 필드 통일(`parameterized`→`isParameterized`, `seamRef`→`seamRefs`), generate-scenarios 스킬 스키마에 `given/when/then`(필수)·`mockTargets` 복원. ingest-specs 스키마에 `acceptanceCriteria.priority/tags` 추가(P0 매핑 규칙의 소비 필드), requirements `text/section` 정렬. test-code-generator에 `projectRoot`/`testSourceRoot` 전달(절대경로 출력의 기준 부재 해소), `stylePolicy` 리터럴 통일(`google-java`), generate-tests 단독 실행 시 `springProfile` 누락 보완. analyze-source 스킬 출력 스키마를 에이전트 정본으로 통일(collaborators `fqcn/role/mockable`, `externalDependencies[]`·exceptionFlows·transactionBoundaries 형상 복원), 3단계 `buildMetadata.springBootVersion` 전달.
  - **8·9단계 구조화 배선(H1)**: full-pipeline 8·9단계에 명시 입력 블록 신설 — `HarnessConfig.coverage/mutation`, `coverageMaxIterations`/`mutationMaxIterations`→`maxIterations`, `targets`→`targetScope` 매핑(고아 필드 해소), **`springProfile`·`existingTestPaths`를 coverage-closer/mutation-analyst까지 전달**(버전 프로파일 없이 신규 테스트를 추측 생성하던 공백 — 7단계와 동일 클래스). measure-coverage/mutation-test의 에이전트 호출을 산문에서 에이전트 입력 스키마 1:1 구조화 프롬프트로 교체.
  - **그린 회귀 + stale runResult 해소(H2)**: 8단계(테스트 추가 후)·9단계(단언 강화 후) 수렴 시 6단계 회귀 실행 → 실패 시 7단계 보정 재진입 → **최종 `runResult` 재할당**을 명문화. 10단계 입력을 "8·9단계 회귀 후 최종값"으로, `generatedFiles`에 8단계 `addedTests` 병합. 기존에는 9단계에서 강화된 단언이 실패해도 10단계가 stale 결과로 `satisfied`를 오판할 수 있었다.
  - **scenarioRef 보존 불변식 확장**: test-fixer에만 있던 "시나리오 테스트 수정 시 `sc001_` 메서드명·javadoc scenarioRef/criteriaRef 보존" 규칙을 coverage-closer·mutation-analyst에도 추가(자체 신규 gap-filling/mutant-killing 테스트는 비시나리오로 scenarioRef 불요 명시).
  - **집계·형상 정합**: PipelineResult 집계 매핑 명시(`coverageResult.coverage.*`·`conformanceResult.totals.*` 중첩 경로), measure-coverage `addedTests`는 closer 출력 object[]에서 경로 flatten임을 명시, `targetScope` 형상을 test-runner 정본(`{classes,packages,methods}`)으로 통일하고 6단계에 `projectRoot` 전달, coverage-closer 자체 `coverage_gate` 호출을 advisory-only로 명시(정본 재측정은 스킬), `refactorAdvisory` 병합 순서(HarnessConfig>HarnessRequest>기본값) 정의, full-pipeline의 `coverage_gate` 파라미터 표기를 실제 서버 시그니처(`klass`)로 정정.
  - **문서 보완**: GUIDE 환경변수 표에 코드가 읽지만 미문서화였던 `REPO_AST_JAVA_BIN`·`TEST_AUTOEVERMATION_HARNESS_NETWORK` 추가.
  - MCP 계층 검증 결과 도구 15종·훅 스크립트 4종·statusline ORDER·주요 파라미터/반환 키 계약은 전부 정합(수정 불요)이었다.

---

## [0.13.2] - 2026-07-04

### Fixed
- **Self-healing 루프의 "기존 테스트 원칙 참조" 배선 보강**: `test-fixer`가 에러 원인(5종 분류)뿐 아니라 **생성 시점 테스트 원칙을 참조해 수정**하도록 명시 연결. `agents/test-fixer.md`에 「테스트 원칙 준수(수정 시 불변 규칙)」 절 신설 — BDD 3단 구조·BDDMockito 스타일·`scenarioRef` 메서드명/javadoc 보존(10단계 verify-scenarios 매핑 의존)·springProfile 관용구(`@MockBean`은 Boot 3.4+ deprecated → `@MockitoBean`, 공식 Spring Framework 문서 근거). 입력에 `springProfile`·`scenarioDocs` 필드 추가(미전달 시 기존 테스트·대상 소스 import를 정본으로 판별). `repair-tests`·`full-pipeline` 7단계 프롬프트를 동일 원칙으로 동기화.
- **full-pipeline 7단계 패치 반영 단계 명시**: `test-fixer`는 `isolation: worktree` 격리 실행이므로 반환된 `patches[]`를 **메인 작업 트리에 적용한 뒤** `run-tests`를 재실행하도록 절차를 명문화(누락 시 동일 실패가 재현되는 배선 공백 제거). `_workspace/07_repair_result.json` 저장 명시.
- **7단계 `relatedSources` 실전달**: 항상 빈 배열이던 것을 `sourceResult`의 실패 대상 FQCN→프로덕션 소스 매핑으로 전달(원인 분석 시 재탐색 비용 제거). `docs/pipeline-flow.md` 7단계 노드 동기화.

---

## [0.13.1] - 2026-07-03

### Added
- **자동 설치 실패 시 사용자 화면 폴백 안내**: SessionStart 훅(`run-server.sh --ensure-only`)이 Python/의존성 준비에 실패하면 **exit 2 + stderr**로 종료해 수동 폴백 명령(OS별 Python 설치 명령 → `pip install -r mcp/requirements.txt` → `/reload-plugins`)이 세션 transcript에 그대로 표시된다(공식 hooks 문서: SessionStart exit 2는 stderr를 사용자에게 표시하고 세션은 계속 진행). 실패 원인별 맞춤 메시지(Python 부재 vs SDK 설치 실패), `HARNESS_AUTO_PYTHON=0` 상태 안내 포함. `bootstrap.py --ensure-only`는 실패 시 exit 1을 반환하도록 변경(호출자가 변환), 데이터 디렉터리 생성 실패도 traceback 대신 한 줄 진단으로 처리. 검증: 성공(exit 0·무출력)/Python 부재(exit 2·안내)/SDK 실패(exit 2·안내) 3경로 실측.

### Changed
- README 사전 요구사항·설치 확인, GUIDE §4.2·트러블슈팅의 Windows 항목을 정확화: **Windows 네이티브 미지원**(MCP 진입점이 POSIX `sh` 기반, Git for Windows도 선택 설치라 `sh` 미보장 — 공식 setup 문서 근거), **WSL에서는 자동 설치 포함 전부 동작**. "수동 Python 설치로 해결" 오해 소지 문구 제거.

### Fixed
- Claude Code가 표준 `hooks/hooks.json`을 자동 로드하는 동작과 중복되지 않도록 `plugin.json`의 명시적 `hooks` 참조를 제거하고, `.lsp.json`을 실제 LSP 서버맵 형태로 보정해 `/reload-plugins` 로드 오류를 방지.

---

## [0.13.0] - 2026-07-03

### Added
- **Python 자동 설치 `mcp/run-server.sh`** (macOS/Linux): 플러그인만 설치하면 Python이 아예 없는 PC에서도 동작한다. MCP 진입점을 POSIX `sh` 스크립트로 교체 — PATH에 Python 3.10+가 있으면 그대로 사용하고, 없으면 uv(공식 standalone installer, **무-sudo**, `~/.local`)로 관리형 Python 3.12를 1회 자동 설치 후 경로를 `${CLAUDE_PLUGIN_DATA}/python-path`에 고정하고 bootstrap.py(v0.12.0 의존성 자동 설치)로 exec한다. 근거: uv 공식 문서(`install.sh` 무-sudo `~/.local/bin` 설치, `uv python install`/`uv python find --managed-python`). 동시 기동(서버 3개+SessionStart 훅) 경쟁은 mkdir 락으로 직렬화(macOS에 `flock` 바이너리 없음). 옵트아웃: `HARNESS_AUTO_PYTHON=0`(수동 설치 안내로 강등). Windows 네이티브는 자동 설치 미지원(수동 설치/WSL 안내). 검증: Python 3.10+ 부재 재현 환경에서 uv 설치 경로 end-to-end(관리형 3.12.12 다운로드 1.25s → venv → initialize 핸드셰이크), 핀 재사용 무소음 재기동, 4-프로세스 동시 기동에서 설치 1회+전원 성공, 옵트아웃 시 명확한 remediation 후 exit 1.

### Changed
- `.mcp.json` 서버 3종 `command`를 `python3` → `sh run-server.sh` 경유로, SessionStart 훅도 동일 진입점(`--ensure-only`, timeout 600s)으로 변경 — E1(Python)+E2(MCP SDK)가 한 진입점에서 보장된다.
- Phase E 정본(environment-setup.md) E1을 assist→auto로 승격하고, `configure-harness`·`full-pipeline` 스킬, README 사전 요구사항("macOS/Linux는 아무것도 미리 설치할 필요 없다"), GUIDE(§4.2·독립 실행·트러블슈팅), DEPENDENCIES.md를 동기화.

---

## [0.12.1] - 2026-07-03

### Changed
- **README 설치 섹션 재구성**: ① 사전 요구사항 표(필수 Python 3.10+ OS별 설치 명령 — brew/apt/winget, 선택 JDK·Maven), ② 마켓플레이스 설치 절차(`/plugin marketplace add` → `/plugin install` → `/reload-plugins`)를 권장 경로로 신설, ③ 설치 확인 절차(MCP 에러 시 진단 순서·수동 폴백·jdtls 안내). `mcp` 패키지는 v0.12.0 자동 부트스트랩이 담당함을 명시.
- **초기 설치 경로에 bootstrap 반영**: Phase E 정본(environment-setup.md)의 E1(OS별 설치 명령 추가)·E2(감지/세팅을 bootstrap 기준으로 — `${CLAUDE_PLUGIN_DATA}/venv`, 시스템 python 비오염, 실패 시에만 pip 폴백)와 `configure-harness`·`full-pipeline` 스킬의 E2 세팅 명령을 동기화.

---

## [0.12.0] - 2026-07-03

### Added
- **MCP 의존성 자동 부트스트랩 `mcp/bootstrap.py`**: 마켓플레이스 설치 직후 사용자가 `pip install`을 몰라도 MCP 서버 3종이 뜨도록, 공식 권장 패턴(plugins-reference의 `${CLAUDE_PLUGIN_DATA}` + SessionStart 훅 diff-manifest 패턴)으로 `mcp[cli]`를 플러그인 데이터 디렉터리의 venv(업데이트에도 유지)에 1회 자동 설치한다. `.mcp.json`의 서버 3종 커맨드가 bootstrap 경유로 변경되고(의존성 보장 후 `os.execv`로 서버 실행), SessionStart 훅(`--ensure-only`, timeout 300s)이 선제 준비/복구를 담당한다. 현재 인터프리터에 이미 `mcp`가 있으면 venv 없이 그대로 실행(기존 환경 존중), 동시 기동 경쟁은 flock으로 직렬화, requirements.txt 변경 업데이트 시 marker 불일치로 자동 재설치, 실패 시 수동 폴백 명령을 stderr 진단으로 안내. 검증: 신규 환경 첫 설치 3.6s(<30s MCP 타임아웃), 3서버 동시 기동 race 테스트에서 설치 1회+전원 initialize 성공.

### Changed
- README·DEPENDENCIES.md·docs/GUIDE.md(§4.2, 트러블슈팅)의 수동 `pip install` 안내를 자동 설치 기준으로 갱신(수동 명령은 오프라인 등 폴백으로 강등).

---

## [0.11.0] - 2026-07-03

### Added
- **상태줄 진행률 표시 `setup-statusline` 스킬 + `scripts/test-autoevermation-statusline.py` 래퍼**: Claude Code statusLine에 `[Test-AutoEverMation#<version>] <pct>% | stage <n>: <name>` 줄을 추가한다(유휴 시 버전만, 완료 시 `100% | done (ok|partial|failed)`). 래퍼는 기존 statusLine 커맨드를 `~/.claude/test-autoevermation-statusline.json`의 delegate로 보존·계속 실행하고(statusLine stdout 다중 줄 렌더링은 공식 문서 재검증, 2026-07-03), 진행률은 대상 프로젝트 `_workspace/` 단계 산출물 존재 여부로 계산한다(orchestration-detail §2 미러 `ORDER` 테이블, 분모 14 — 조건부 7단계 제외, "존재하는 최고 산출물" 기준이라 3.5 스킵·1∥2 병렬 순서 역전에 안전). delegate 실패↔TAM 계산 실패 상호 격리·항상 exit 0. 스킬은 설치(백업·멱등·이중 래핑 방지)/경로 갱신/제거(원복)를 담당. 플러그인은 메인 statusLine을 설정할 수 없으므로(공식: 플러그인 settings.json은 `agent`/`subagentStatusLine`만 적용) 사용자 승인형 스킬 방식 채택.
- **동작 원리·사용법 종합 가이드 `docs/GUIDE.md`**: 아키텍처(스킬 13·에이전트 11·MCP 3종·훅)·파이프라인 단계별 상세·설치·대화형/CI 사용법·설정(`HarnessRequest`/`HarnessConfig`/환경변수)·산출물 해석·보안 모델·트러블슈팅·문서 지도를 한 문서로 정리. Claude Code 플러그인/마켓플레이스·MCP SDK 서술은 공식문서로 재검증(2026-07-02). 루트·플러그인 README에서 링크.
- **3.5단계 리팩토링 권고 게이트**: 코드 분석(3단계)과 시나리오 생성(4단계) 사이에서 테스트 부적합 코드를 판정한다 — ① 순환복잡도 초과(NIST SP 500-235 기준, 기본 CC>10), ② 테스트 저해 설계(강결합·정적/숨은 의존·생성자 부작용·미주입 clock/random — Spring 공식 생성자 주입 권고, Mockito javadoc §39/§48, Google Testing 가이드 근거), ③ 비효율(N+1·루프 내 쿼리 — Hibernate userguide Fetching 장 근거). 플래그된 대상은 공식문서 인용을 담은 권고 문서(`test_docs/refactoring/RA-*.md` + INDEX)를 **항상** 작성하고, 대화형은 `AskUserQuestion`(전체 포함/일부 제외/전체 제외)으로 테스트 생성 대상 포함 여부를 결정한다(제외분은 4단계 입력에서 필터링, 권고 문서는 보존). 비대화형·CI는 전 대상 포함+경고. 신규 산출물: `agents/refactor-advisor.md`(read-only), `skills/refactor-advisory/SKILL.md`, `references/refactor-advisory.md`(SSOT), fallback-policy **#19**, `_workspace/03b·03c`, `HarnessConfig.refactorAdvisory{enabled,thresholds}`(인터뷰 비침습 — `HarnessRequest`로만 오버라이드).

### Removed
- **개발용 검증 아카이브 `result_report/` 전체 제거**(저장소 루트 — `docs/REPORT.md`·`VERIFICATION.md`·`PRINCIPLES_AUDIT.md`·README, 스스로 "런타임에는 필요 없음" 명시분): 이를 가리키던 문서 포인터(루트/플러그인 README, `mcp/repo_ast_server.py` docstring)도 함께 정리. 핀 고정 버전·API 근거는 `RESEARCH_NOTES.md`가 계속 담당하며 런타임 동작 변화 없음.
- 미사용·중복 스크립트 삭제: `scripts/detect-build-tool.sh`·`scripts/run-tests.sh`·`scripts/collect-test-reports.py`(로직이 build-test MCP 서버에 내장되어 대체됨)와, 어디서도 호출되지 않던 고아 스크립트 `scripts/postprocess-report.py`.
- `.mcp.json`에서 어떤 코드도 읽지 않던 죽은 env 제거: `REPO_AST_NETWORK`, `SPEC_DOC_NETWORK`.
- 죽은 코드/임포트 제거: `repo_ast_server`의 미사용 `import sys`, `spec_doc_server`의 미사용 `import uuid`, 도달 불가능한 정규식 분기(`when\s`·`해야\s*한다`).
- 개발용 검증 스캐폴딩 제거(검증 후): `result_report/verification/*.py`와 `result_report/sample-*` 샘플 프로젝트.

### Changed
- MCP 서버 3종 구조화(외부 동작·도구 시그니처·출력 스키마 보존): 리포트 탐색기 3종(`_find_reports`)·XML 파싱 오류 처리(`_safe_parse_xml`)·프로파일 충돌 감지(`_profile_conflict`) 중복 통합, 과대 함수 분리(`detect_build_capabilities`→`_gradle_capabilities`/`_maven_capabilities`, `run_targeted_tests`→`_build_test_command`/`_classify_run_status`, `extract_acceptance_criteria`→`_strip_prohibition`).
- `repo_ast_server._jdk_available()` 메모이즈(`functools.lru_cache`) — JDK 가용성은 프로세스 내 불변이므로 실패 경로의 중복 `java -version` probe를 1회로 축소(동작 동일).
- `configure-harness/SKILL.md` 중복 축소: 출력 봉투의 `harnessConfig` 전체 필드(~46줄) 재기재를 제거하고 「5단계」 스키마를 SSOT로 가리키도록 정리(봉투 키는 유지 — 스킬 단독 가독성 보존).
- `.mcp.json`에 `SPEC_DOC_WORKSPACE=${CLAUDE_PROJECT_DIR}` 추가 — 문서화돼 있었으나 미설정이라 무효였던 spec-doc 워크스페이스 경로 봉쇄 가드를 활성화(`repo-ast`의 `REPO_AST_ALLOW_ROOT`와 정합).
- 오해 소지 docstring 수정(`_run_subprocess`의 "network-off env merge"), `REPORT.md` 참조를 실제 위치 `result_report/docs/REPORT.md`로 정정.

### Fixed
- 오케스트레이션 문서의 사실 오류·중복 조건 정리: 존재하지 않는 task `integration-test`(→ `integrationTest`/`verify`), build-test가 내보내지 않는 `-pl/-am` 예시, Phase-E 게이트 4종 불일치를 SSOT(`references/environment-setup.md`)로 통일, analyze-ast 단계 번호·mutation `maxIterations`·`maxRepairRetries` 표현·Awaitility 모순 정정.
- JavaParser CLI(`AstCli.java`) 디렉터리 모드 패키지 버그: 디렉터리를 넘기면 첫 파일의 `package`만 읽어 다른 패키지 클래스의 FQCN이 틀리던 문제를, `package`를 컴파일 단위(파일)별로 해석해 각 클래스에 부여하도록 수정(JavaParser `CompilationUnit`은 파일 단위 API). Python `_normalize_java_cli_output`는 클래스별 `package`를 우선 사용(단일 파일 하네스 경로는 동작 동일 — jar 재빌드 필요, shaded jar은 빌드 산출물이라 미포함).

### Evidence
- **3.5단계 스모크 테스트(2026-07-02, 로컬)**: 알려진 결함을 심은 스크래치 샘플 8클래스(CC=14 메서드·루프 내 `findById` N+1·생성자 `new`/`connect()` 실질 작업·싱글턴 `getInstance()`·미주입 `LocalDateTime.now()`/`new Random()`·클린 클래스 1)를 repo-ast `_analyze`(JavaParser jar 경로, `degraded:false`)로 추출한 뒤 refactor-advisory.md §2 기준으로 판정 — 13/13 체크 통과: 3범주(complexity/testability/efficiency) 기대 신호 전부 검출, §2.4 규칙대로 RA-001 `severity: high`, 클린 클래스 오탐 0건(`cleanTargets`), 출력은 `RefactorAdvisoryResult` 스키마 정합(파일:라인 evidence, 소스 원문 미포함). 샘플·산출 JSON은 배포물 비포함(스크래치 디렉터리).

---

## [0.10.0] - 2026-07-02

### Changed
- **플러그인 이름 변경 (BREAKING)**: `spring-test-harness` → `test-autoevermation-harness-plugin`. 플러그인 식별자(`plugin.json`/`marketplace.json` name)·디렉터리(`spring-test-harness-plugin/` → `test-autoevermation-harness-plugin/`)·스킬 네임스페이스(`/spring-test-harness:<skill>` → `/test-autoevermation-harness-plugin:<skill>`)가 모두 바뀐다. 근거: 공식 플러그인 레퍼런스 — plugin name은 kebab-case 필수이며 컴포넌트 네임스페이스로 사용되고, 마켓플레이스 항목 name이 설치 식별자다(2026-07-02 재검증).
- 환경변수 rename: `SPRING_TEST_HARNESS_NETWORK` → `TEST_AUTOEVERMATION_HARNESS_NETWORK`, `SPRING_TEST_HARNESS_TEST_SCOPE` → `TEST_AUTOEVERMATION_HARNESS_TEST_SCOPE` (가드 훅 `scripts/guard-network.py`·`scripts/guard-read.py`, `settings.json`).
- Python 패키지 rename: `spring-test-harness-mcp` → `test-autoevermation-harness-mcp`, console scripts `spring-harness-*` → `test-autoevermation-harness-*` (`mcp/pyproject.toml`, 버전 0.10.0 동기화).
- 훅·MCP 사용자 노출 메시지 접두어를 새 플러그인 이름으로 통일.

### Migration
- 기존 설치자는 재설치 필요: `/plugin uninstall spring-test-harness` 후 `/plugin marketplace update`, `/plugin install test-autoevermation-harness-plugin@test-autoevermation-harness`.
- `SPRING_TEST_HARNESS_NETWORK=on` 등 기존 환경변수를 설정해 둔 경우 새 변수명으로 교체해야 한다.

---

## [0.8.0] - 2026-06-28

### Added

- **대상 빌드 능력 프로비저닝(F1) + 의존성 캐시 프라이밍(F2)**: 신규 SSOT
  [`references/build-provisioning.md`](references/build-provisioning.md). Phase E가 하네스 런타임만 세팅하던
  공백을 메워, **대상 프로젝트 빌드 파일**이 커버리지/뮤테이션을 낼 수 있는지와 콜드 캐시 첫 실행을 선제 처리한다.
  - **`build-test` MCP 신규 도구 2종(신호 전용, 파일 미수정)**:
    - `detect_build_capabilities(root, junit_engine)` — JaCoCo 플러그인/**XML 활성화**·PITest 플러그인/JUnit5
      플러그인 유무를 감지해 `missing[]` + 최소 `proposedChanges[{file,anchor,snippet,reason,source}]` 반환.
    - `check_dependency_cache(build_tool, root)` — 공유 캐시 유무로 `primed` 추정 + 1회 프라이밍 권고.
  - **`run_targeted_tests(..., online=True)`**: 콜드 캐시/신규 플러그인 해석을 위한 **1회 네트워크-ON** 프라이밍 경로
    (이후 호출은 다시 오프라인). 기본은 종전대로 오프라인(보안 #14 유지).
  - **0.6단계(configure-harness)**: 0.5 프로파일 확정 직후·6단계 run-tests 이전에 `detect→approve→inject`로
    빌드 능력을 확정하고(대화형=`AskUserQuestion` 승인 후 스니펫 주입+`buildChanges[]` 기록 / CI=자동 주입 금지·
    remediation 중단), 캐시 프라이밍을 결정한다.

### Changed

- `references/environment-setup.md`: 체크리스트에 **E11(빌드 능력)·E12(캐시 프라이밍)** 추가, 통과 기준에 0.6단계 명시.
- `references/fallback-policy.md`: **#17(빌드 능력 미비 — detect→approve→inject)·#18(콜드 캐시 — 1회 온라인 프라이밍)** 추가.
- `configure-harness`: **0.6단계**(빌드 능력 프로비저닝 + 캐시 프라이밍) 신설, 실패표에 #17·#18 행 추가.
- `full-pipeline`: Phase E 목적/항목에 E11·E12 반영, 6단계에 콜드 캐시 1회 `online=True` 프라이밍 주석, 실패표에
  #17·#18 행 추가.
- `plugin.json`·`marketplace.json` 0.7.0 → 0.8.0.

### Evidence

- 공식문서(웹 검증 2026-06-28): Gradle JaCoCo 플러그인은 `jacocoTestReport`를 자동 생성하나 **XML 출력 기본 OFF**
  (`reports { xml.required = true }` 필요) — [Gradle JaCoCo Plugin](https://docs.gradle.org/current/userguide/jacoco_plugin.html).
  PITest `pitest` 태스크는 `info.solidsoft.pitest` 플러그인 필요, Jupiter는 `junit5PluginVersion`(pitest-junit5-plugin) —
  [gradle-pitest-plugin](https://gradle-pitest-plugin.solidsoft.info/), [pitest-junit5-plugin](https://github.com/pitest/pitest-junit5-plugin).
  Maven JaCoCo는 `prepare-agent`+`report`(verify) 골 — [JaCoCo Maven Plug-in](https://www.eclemma.org/jacoco/trunk/doc/maven.html).
  Gradle `--offline`은 **미캐시 모듈 시 빌드 실패** — [Gradle Dependency Caching](https://docs.gradle.org/current/userguide/dependency_caching.html).
  Maven `dependency:go-offline`은 의존성+플러그인 일괄 다운로드 — [dependency:go-offline](https://maven.apache.org/plugins/maven-dependency-plugin/go-offline-mojo.html).

---

## [0.7.0] - 2026-06-27

### Added

- **시나리오 승인 게이트 + 적합성 검증 + `test_docs/`(SSOT)**: 신규 레퍼런스
  [`references/scenario-docs.md`](references/scenario-docs.md). 시나리오를 **사용자 승인 후** 테스트로 생성하고,
  모든 과정이 끝나면 **시나리오 충족 여부를 검증**해 대상 프로젝트의 `test_docs/`에 living documentation으로 정리한다.
  - **승인 게이트(4.5단계)**: 시나리오 설계 직후·테스트 생성 전에 `test_docs/scenarios/<id>.md`(`approval: pending`)로
    저장하고 **대화형=`AskUserQuestion`**(전체 승인/일부 제외·수정/재설계), **CI=자동 승인+기록**. 승인분만 생성으로 진행,
    제외분은 `excluded`로 보존(추적성).
  - **적합성 검증(10단계, 마지막)**: 신규 스킬 `verify-scenarios` + 신규 에이전트 `scenario-conformance-verifier`.
    `scenarioRef`(메서드명 `sc001_…` + javadoc)로 시나리오↔테스트를 매핑하고 satisfied/unsatisfied/missing 판정.
    `// then` 단언이 시나리오 then을 빠짐없이 반영해야 satisfied. `unmet` 존재 시 `status: partial` + 잔여 전량 보고.
  - **산출물**: `test_docs/INDEX.md`(시나리오↔테스트코드↔결과 매핑 표) + `test_docs/scenarios/<id>.md`(시나리오별 파일).
    사람이 읽는 영속 산출물이라 대상 프로젝트에 커밋 가능(`_workspace/` 중간 JSON과 분리).

### Changed

- `full-pipeline`: 4.5단계(승인 게이트+`test_docs/` 저장)와 10단계(`verify-scenarios` 적합성 검증)를 추가.
  5단계 입력을 `scenarioResult.scenarios` → **`approvedScenarios`**(승인분)로 변경. 출력 스키마에 `scenarioApproval`·
  `verifyScenarios`·`scenarioDocs` 추가. 보고서에 시나리오 적합성 섹션 추가. 실패표에 #15·#16 행 추가.
- `generate-scenarios`: 출력이 바로 생성으로 가지 않고 4.5단계 승인 게이트를 거친다는 다운스트림 주석 추가(스킬 자체는 read-only).
- `orchestration-detail.md`: `_workspace/`에 `04b_approval.json`·`10_conformance.json` 추가, `test_docs/` 영속 산출물
  규칙 명시, 부분 재실행 매트릭스에 시나리오/적합성 행 추가.
- `references/fallback-policy.md`: #15(시나리오 승인 게이트 — 대화형 AskUserQuestion/CI 자동 승인), #16(적합성 미충족 →
  partial) 추가.
- `README.md`: 파이프라인 4.5·8·9·10단계 반영, Skills 11→12·Agents 9→10, 시나리오 승인·적합성·`test_docs/` 절 추가.
- `plugin.json`·`marketplace.json` 0.6.0 → 0.7.0.

### Evidence

- 설계 근거(웹 검증 2026-06-27): BDD/Living Documentation는 테스트 스위트에서 생성되어 항상 최신인 실행 가능 명세이며
  요구사항을 안정적 ID로 테스트에 묶어 추적성을 제공 — Serenity BDD Living Documentation, Cucumber "How does BDD
  affect traceability", JUnit 5 `@DisplayName`(리포팅 추적성). 본 하네스의 기존 추적성(시나리오 BDD given/when/then +
  메서드명 `scenarioRef` + javadoc `criteriaRef`)을 사람이 읽는 `test_docs/`로 외부화한 것.

---

## [0.6.0] - 2026-06-27

### Added

- **환경 세팅 선(先)처리 — Phase E 체크리스트(SSOT)**: 신규 레퍼런스
  [`references/environment-setup.md`](references/environment-setup.md). 하네스가 fallback을 파이프라인
  도중에 "마주치기" 전에, 시작 시점에 **TODO 리스트로 환경을 전부 선세팅**한다.
  - 항목: E1 Python 3.10+ · E2 MCP SDK · E3 MCP 서버 등록 · E4 JDK 17+ · E5 Maven 3.6.3+ ·
    E6 JavaParser CLI jar · E7 JDT LS+Java21 · E8 빌드도구 · E9 Spring 프로파일 ·
    **E10 테스트 실행 JDK↔Mockito 호환**(JDK 24/25 inline mock-maker 위험 선점검).
  - **세팅 방식**: 자동 가능 항목(E2 `pip install`, E6 `mvn package`)은
    **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / 비대화형·CI=자동 세팅** 후 재검증.
    assist/비결정적 항목은 대화형=안내 질문, CI=하드 중단(remediation).

### Changed

- `configure-harness`: 기존 Preflight를 **Phase E 환경 세팅 체크리스트(TodoWrite 기반)**로 확장 —
  단순 점검·하드중단에서 **함께 세팅(대화형)/자동 세팅(CI)**으로 전환.
- `full-pipeline`: 0단계 이전에 **Phase E 환경 세팅** 단계를 명시(선행 게이트).
- `references/fallback-policy.md`: 공통규칙 2·비대화형 감지 갱신(결정적 환경 항목은 CI에서 **자동 세팅**),
  표 #1·#2·#3·#4·#5·#6을 Phase E 선세팅으로 재정의 + E10 등 추가 환경 항목 주석.
- `mcp/javaparser-cli/README.md`: jar를 **"권장(Phase E·E6 best-effort 빌드)"**로 정정 — 기본 배포는
  jar 부재 시 정규식 fallback으로 degrade(`REPO_AST_REQUIRE_JAVAPARSER=1`은 opt-in 하드실패).
- `plugin.json`·`marketplace.json` 0.5.0 → 0.6.0.

### Evidence

- 세팅 명령·요구사항 사실 확인: `mcp/requirements.txt`(`mcp[cli]>=1.2.0`),
  `mcp/javaparser-cli/README.md`(`mvn -q -DskipTests package` → `astcli-1.0.0-shaded.jar`, JDK 17+),
  `.lsp.json`(jdtls, Java 21+). Eclipse JDT LS 구동 Java 21+ 요구(2025-03 SDK 4.35);
  Mockito/ByteBuddy Java 25(class-file 69) 미지원(≤5.13) → Mockito 5.16+/ByteBuddy 1.17+ 또는
  `-Dnet.bytebuddy.experimental=true` 필요.

---

## [0.5.0] - 2026-06-26

### Added

- **커스텀 컴포넌트 인식(메타 애노테이션 전이 해석)**: `repo-ast-mcp`가 분석 파일군의
  `@interface` 선언을 스캔해 메타 애노테이션을 **전이적으로** 해석한다(`_build_meta_index`).
  - 커스텀 스테레오타입(`@UseCase` ← `@Component`, 거리 2 `@ReadModel → @UseCase → @Component`
    포함)이 `pojo`가 아니라 controller/service/repository/component로 분류되고
    `list_spring_components` 자동탐지에 포함된다(specialization 우선순위 적용).
  - **합성 매핑 애노테이션**(`@GetJson` ← `@RequestMapping`)을 식별해 해당 컨트롤러 엔드포인트에
    `riskPoints` 경고("composed mapping … confirm URL path/HTTP method")를 남긴다.
- 신규 레퍼런스 [`references/custom-components.md`](references/custom-components.md)(SSOT) +
  실 샘플 `result_report/sample-custom-components/`(커스텀 스테레오타입·합성 매핑·`ConstraintValidator`)
  + 드라이런 `result_report/verification/dryrun_custom_components.py` (개발 저장소 상위 경로 — 배포물 미포함).

### Fixed

- **정규식 폴백 메서드 추출 버그**: `@PathVariable("id")`/`@RequestParam(value=…)`처럼 인자가 있는
  파라미터 애노테이션이 메서드 파라미터 목록을 조기 절단해 컨트롤러 엔드포인트가 통째로 누락되던
  문제 수정(`_METHOD_RE`가 한 단계 중첩 괄호 허용). JavaParser jar 미빌드 기본 경로에서 발생.

### Changed

- `ast-structure-analyzer`·`source-code-analyzer`·`test-code-generator`에 커스텀 스테레오타입/합성
  매핑/커스텀 인프라(validator·converter·interceptor) 처리 지시문 추가.
- `plugin.json`·`marketplace.json` 0.4.0 → 0.5.0.

### Evidence

- `dryrun_custom_components.py --expect=fixed`: `@UseCase`/`@ReadModel` → component+자동탐지,
  합성 매핑 flagged, validator는 pojo 타깃 유지 — 전부 MATCH. 기존 boot2/boot4 샘플 회귀:
  표준 스테레오타입 분류 유지, 내장 `@GetMapping`은 합성 매핑으로 오탐하지 않음.

---

## [0.4.0] - 2026-06-26

### Added

- **BDD 구조화(시나리오 + 테스트 본문)**: 시나리오 객체에 `given`(string[]) / `when`(string) /
  `then`(string[]) 필드를 추가하고 필수화(`scenario-generator`, `generate-scenarios`). 생성 테스트
  본문은 **`// given` → `// when`(단일 행위, 결과 캡처) → `// then`** 3단 섹션으로 작성한다(예외 검증은
  `// when & then` 병합 허용). 협력 stub은 BDDMockito `given().willReturn()/willThrow()`.
- **메서드명에 scenarioRef 포함**: 테스트 메서드명을 **`<scenarioRefSlug>_<행위>`** 형식으로 생성
  (`SC-001` → `sc001_...`). criteriaRef/scenarioRef는 javadoc에도 계속 기록해 추적성 유지.

### Changed

- `test-code-generator`·`generate-tests`·`full-pipeline`에 메서드 네이밍 규칙과 BDD 본문 구조 규칙 추가.
- 예제 동기화: `examples/java/OrderControllerTest.java`(+boot2 jupiter/junit4), `OrderAmountCalculatorTest.java`,
  `examples/json/scenario-example.json`(given/then 배열화)와 `sample-spring-boot2`의 생성 테스트를
  scenarioRef 접두 + given/when/then 구조로 갱신. **Boot 2.7.18 실 빌드 재검증: Tests run 9, Failures 0**.
- `plugin.json`·`marketplace.json` 0.3.0 → 0.4.0.

### Notes

- TDD(red-green-refactor) 모드는 이번 범위에서 도입하지 않음(사용자 결정). 본 하네스는 기존 코드 대상
  spec/characterization 기반 사후 테스트 생성이며, BDD 표현(Given/When/Then)만 강화했다.

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

[Unreleased]: https://github.com/1223v/test-autoevermation-harness/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/1223v/test-autoevermation-harness/compare/v0.8.0...v0.10.0
[0.1.0]: https://github.com/1223v/test-autoevermation-harness/releases/tag/v0.1.0
