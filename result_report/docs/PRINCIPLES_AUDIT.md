# 참고 하네스(revfactory/harness) 설계 원칙 준수 감사

> 기준: `github.com/revfactory/harness` (clone 후 전문 분석). 근거 파일 —
> `skills/harness/SKILL.md`, `references/agent-design-patterns.md`,
> `references/orchestrator-template.md`, `references/skill-writing-guide.md`,
> `references/skill-testing-guide.md`, `references/qa-agent-guide.md`.
> 대상: 본 `spring-test-harness-plugin` (v0.2.0).
> 감사일: 2026-06-25.

참고 하네스는 "팀 아키텍처 팩토리"(도메인→전문 에이전트 팀 생성)이고 본 플러그인은 "Spring 테스트 생성 하네스"로 목적은 다르나, **오케스트레이션 설계 원칙**은 그대로 적용 대상이다. 아래는 원칙별 준수 여부와 근거다.

## 준수 매트릭스

| # | 참고 원칙 (출처) | 본 플러그인 상태 | 판정 |
|---|---|---|---|
| 1 | **6대 아키텍처 패턴** 선택 (agent-design-patterns.md) | full-pipeline = 파이프라인 + 팬아웃/팬인(ingest∥ast) + 생성-검증(generate→run→repair, coverage-closer/mutation-analyst 루프) | ✅ 준수 |
| 2 | **에이전트=파일 정의, 인라인 금지** (SKILL.md Phase3, patterns "에이전트 정의 구조") | 9개 에이전트 전부 `agents/*.md` 파일, 인라인 역할 주입 없음 | ✅ 준수 |
| 3 | **단일 역할·분리 기준**(전문성/병렬성/컨텍스트/재사용) | 분석(ast/source/spec)·생성·실행·보정·커버리지·뮤테이션을 1역할 1에이전트로 분리 | ✅ 준수 |
| 4 | **읽기 전용 분석은 읽기 권한으로** (patterns "에이전트 타입 선택") | 분석 3종 read-only(Write/Edit/Bash deny), 생성/실행/보정만 write/exec | ✅ 준수(초과 달성) |
| 5 | **생성-검증 최대 재시도(2~3)로 무한루프 방지** (patterns §4) | repair `maxRepairRetries=2`, coverage/mutation `maxIterations` 한도 | ✅ 준수 |
| 6 | **Pushy description** (skill-writing-guide §1) | 각 스킬 description에 동작+트리거 상황 기술, 키워드 다수 | 🟡 부분(아래 9와 연동) |
| 7 | **Why-first / 명령형 / 일반화** 본문 (skill-writing-guide §2) | 본문 명령형·근거 제시·금지사유 명시(flaky 등) | ✅ 준수 |
| 8 | **Progressive Disclosure: 본문<500L, 상세는 references/** (SKILL.md §4-4, guide §5) | references/ **없음**. full-pipeline 455L·configure-harness 348L로 비대 | 🔴 **갭** → 개선 1 |
| 9 | **후속/재실행 트리거 키워드**(재실행·수정·보완) (orchestrator-template "후속 키워드") | full-pipeline description에 재실행 의미 키워드 **불충분** → 1회성 위험 | 🔴 **갭** → 개선 2 |
| 10 | **오케스트레이터 Phase 0 컨텍스트 확인 + `_workspace/` 파일 기반 전달** (orchestrator-template Phase 0/5-1) | `_workspace/` 규약·부분 재실행 분기 **없음**. 결과를 메인 컨텍스트로 전달 | 🔴 **갭** → 개선 3 |
| 11 | **에러 핸들링: 1회 재시도 후 누락 명시, 상충은 출처 병기·미삭제** (orchestrator §5-2) | full-pipeline 실패 표에 단계별 처리 명시, repair 재시도 | ✅ 준수 |
| 12 | **타이밍/토큰 계측(timing.json: total_tokens/duration_ms)** (skill-testing-guide §3-3, schema §7) | 서브에이전트 완료 알림의 `total_tokens`/`duration_ms`를 **미수집** | 🔴 **갭** → 개선 4 |
| 13 | **데이터 스키마 표준(text/passed/evidence)** (skill-writing-guide §7) | 본 플러그인은 status/summary/evidence/... 자체 표준 사용(일관) | 🟢 동등(자체 표준 일관 유지) |
| 14 | **QA: 양쪽 동시 읽기·교차 비교·점진 검증** (qa-agent-guide) | test-fixer가 실패↔소스 교차, coverage/mutation 점진 루프 | ✅ 준수 |
| 15 | **에이전트 팀 기본 모드** (SKILL.md Phase2-1) | 전부 서브에이전트(`Task`) 모드, TeamCreate 0 | 🟡 **의도적 분기**(아래 근거) |
| 16 | **모든 에이전트 opus** (patterns "모델") | v0.2.1부터 전 에이전트·Task 호출 `model: inherit`(현재 세션 모델) — opus 강제 제거 | 🟢 **이식성 우선**(opus 없는 환경 지원) |
| 17 | **CLAUDE.md 하네스 포인터 등록** (SKILL.md §5-4) | 미등록(플러그인 namespace 자동 트리거로 대체) | 🟡 선택(낮은 우선순위) |
| 18 | **하네스 진화 루프(Phase7) / eval baseline 비교** | 미도입 | 🟡 선택(성능 아닌 품질 운영) |

## 의도적 분기의 근거 (성능 관점에서 "그대로 두는 것이 옳음")

- **#15 서브에이전트 vs 에이전트 팀**: 참고 하네스도 의사결정 트리에서 *"팀 통신이 정말 불필요한가?"*를 자문하라고 한다(patterns "모드 선택"). 본 파이프라인의 병렬 구간(`ingest-specs ∥ analyze-ast`)은 **상호 통신이 불필요한 완전 독립 작업**이며, 이후는 순차 의존이다. 에이전트 팀은 `TeamCreate`+`SendMessage` 조율·브로드캐스트로 **토큰 비용과 지연이 더 크다**(patterns "제약: 토큰 비용 높음"). 따라서 서브에이전트 팬아웃이 **더 빠르고 저렴한 올바른 선택**이다. 단, 참고 원칙은 "서브 선택 시 근거 명시"를 요구하므로 → 개선에서 full-pipeline에 **실행 모드 + 근거를 명시**한다.
- **#16 모델 티어 → 이식성(v0.2.1 변경)**: 초기에는 분석=sonnet/생성=opus로 티어링했으나, **opus를 사용할 수 없는 환경**을 지원하기 위해 전 에이전트 frontmatter와 모든 `Task(...)` 호출의 `model`을 `inherit`(현재 세션 모델)로 통일했다. 이제 하네스는 사용자가 어떤 모델을 쓰든 그 모델로 동작한다(opus 강제 없음). 특정 티어를 강제하려면 해당 에이전트/호출에 `model`을 명시 pin하면 된다.

## 선별한 성능 개선 (코드에 미도입 → 도입)

성능/효율에 직결되고 아직 코드에 없는 4가지만 선별한다(품질-운영용인 eval baseline·진화 루프·CLAUDE.md 포인터는 이번 범위 제외, 선택 항목으로 기록).

| 개선 | 무엇이 빨라지나 | 근거 |
|---|---|---|
| **1. Progressive Disclosure (references/ 분리)** | 스킬 트리거 시 로드되는 **컨텍스트 토큰 감소**(본문 lean). full-pipeline/configure-harness 상세를 references/로 이동 | SKILL.md §4-4, guide §5 ("컨텍스트 윈도우는 공공재") |
| **2. 후속/재실행 트리거 키워드** | 1회성 사장(dead code) 방지 → **부분 재실행 경로가 실제로 트리거**됨 | orchestrator-template "후속 키워드" |
| **3. `_workspace/` 파일 기반 전달 + Phase 0 부분 재실행** | (a) 변경 단계만 재실행 → **전체 파이프라인 재실행 회피**, (b) 대용량 결과를 파일로 전달 → **메인 컨텍스트 오염/토큰 절감** | orchestrator-template Phase 0, §5-1 |
| **4. timing.json 계측(total_tokens/duration_ms)** | 단계별 토큰/지연 가시화 → **느린·비싼 단계 식별 후 튜닝** 가능. 알림 시점에만 접근 가능한 값 즉시 저장 | skill-testing-guide §3-3, schema §7 |

> 위 4개는 본 문서의 개선 1~4로 구현하고, 적용 후 본 표의 #8/#9/#10/#12 판정을 ✅로 갱신한다.

---

## 개선 적용 결과 (2026-06-25)

| 갭 | 개선 | 적용물 | 상태 |
|---|---|---|---|
| #8 Progressive Disclosure | 1 | `skills/full-pipeline/references/orchestration-detail.md` 신설, 본문 472L(<500) 유지, 포인터로 조건부 로드 | ✅ 해소 |
| #9 후속/재실행 키워드 | 2 | full-pipeline description에 "재실행/부분 재실행/결과 개선/보완/업데이트/…만 다시" 추가 | ✅ 해소 |
| #10 `_workspace/`+Phase 0 부분 재실행 | 3 | 본문에 실행 모드·`_workspace/` 규약·Phase 0 분기, 상세는 reference. `.gitignore`에 `_workspace/` | ✅ 해소 |
| #12 timing.json 계측 | 4 | `scripts/record-timing.py`(stdlib) + reference의 timing 스키마. 단계별 토큰/시간 누적·slowest/most_expensive 산출 | ✅ 해소 |

**#15 서브에이전트는 성능상 유지**하되 full-pipeline에 실행 모드와 근거를 명시했다(참고 하네스의 "서브 선택 시 근거 명시" 요건 충족). **#16 모델은 v0.2.1에서 `inherit`로 전환** — opus 강제를 제거해 어떤 모델 환경에서도 동작하도록 했다.

**이번 범위 외(선택, 품질-운영용):** #17 CLAUDE.md 포인터, #18 진화 루프 / eval baseline 비교 — 성능이 아닌 운영 품질 항목이라 보류.
