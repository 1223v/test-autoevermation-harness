# 파이프라인 흐름도 (Mermaid)

이 문서는 `test-autoevermation-harness-plugin` 플러그인이 **어떤 흐름으로 구동되는지**를 Mermaid 다이어그램으로 정리한 것이다.
정본(텍스트): [skills/full-pipeline/SKILL.md](../skills/full-pipeline/SKILL.md) ·
[references/environment-setup.md](../references/environment-setup.md) ·
[references/refactor-advisory.md](../references/refactor-advisory.md) ·
[references/scenario-docs.md](../references/scenario-docs.md) ·
[references/fallback-policy.md](../references/fallback-policy.md).

> 표기 규칙: 사각형=처리 단계, 마름모=의사결정/게이트, 둥근모서리=시작/종료. 점선 화살표=루프/되돌아감.
> 대화형(사람 있음)은 `AskUserQuestion`, 비대화형·CI(`claude -p`)는 자동 세팅 또는 하드 중단으로 분기한다.

---

## 1. 전체 파이프라인 (end-to-end)

```mermaid
flowchart TD
    A(["HarnessRequest 입력"]) --> B["전처리: 입력 정규화"]
    B --> C["Phase E — 환경 세팅 (선행 필수, TodoWrite)<br/>E1~E7 + E10 점검"]
    C --> D{"환경 통과?<br/>필수 E1·E2·E3+E10 completed<br/>(E8·E9는 0.5단계 · E4~E7 선택/degrade)"}
    D -- "아니오" --> X1(["status: failed — 파이프라인 미시작<br/>+ remediation 안내"])
    D -- "예" --> E["0단계 — configure-harness<br/>0.5 프로파일 감지 → 인터뷰 → HarnessConfig"]

    E --> E6{"0.6 빌드 능력/캐시 (E11·E12)<br/>detect_build_capabilities · check_dependency_cache"}
    E6 -. "누락: 대화형=승인 주입 / CI=remediation 중단" .-> E6
    E6 --> F1["1단계 — ingest-specs<br/>(spec-reviewer)"]
    E6 --> F2["2단계 — analyze-ast<br/>(ast-structure-analyzer)"]
    F1 --> G["3단계 — analyze-source<br/>(source-code-analyzer)"]
    F2 --> G
    G --> G35{"3.5 — 리팩토링 권고 게이트<br/>(refactor-advisor) 플래그 시 RA-*.md 작성<br/>대화형=포함/제외 질문 · CI=전 대상 포함+경고"}
    G35 -- "포함 대상만 (필터본)" --> H["4단계 — generate-scenarios<br/>(scenario-generator) → ScenarioSet (BDD)"]
    G35 -- "전 대상 제외" --> X35(["status: partial — '생성 대상 없음(전량 리팩토링 권고)'"])

    H --> I["4.5 — 시나리오 저장<br/>test_docs/scenarios/&lt;id&gt;.md (approval: pending) + INDEX.md"]
    I --> J{"승인 게이트<br/>대화형=AskUserQuestion / CI=자동 승인"}
    J -. "재설계 요청" .-> H
    J -- "승인분만 (approvedScenarios)" --> K["5단계 — generate-tests<br/>(test-code-generator) → src/test/java/*"]

    K --> L["6단계 — run-tests<br/>(test-runner)"]
    L --> M{"실패 있음?"}
    M -- "예" --> N["7단계 — repair-tests<br/>(test-fixer) 원인 분류 → 최소 diff 보정<br/>(생성 원칙·scenarioRef 보존) → patches[] 메인 반영"]
    N -. "그린까지 재시도<br/>(무진전 3회 → partial)" .-> L
    M -- "아니오 (그린)" --> O["8단계 — measure-coverage<br/>(coverage-closer) near-100% 게이트 루프"]

    O --> P["9단계 — mutation-test<br/>(mutation-analyst) PITest 강화 루프"]
    P --> Q["10단계 — verify-scenarios<br/>(scenario-conformance-verifier)"]
    Q --> R{"승인 시나리오 전부 satisfied?<br/>given/when/then 충족"}
    R -- "아니오 (unmet: unsatisfied/missing)" --> S(["status: partial<br/>잔여 전량 보고 + test_docs/ 갱신"])
    R -- "예" --> T(["status: ok<br/>PipelineResult + 보고서 + test_docs/INDEX.md"])

    O -. "미달 시 추가 테스트 → 재측정" .-> O
    P -. "survivor 강화 → 재실행" .-> P
```

> 1·2단계는 **병렬**(서브에이전트 팬아웃)이라 `E`에서 두 갈래로 갈라져 `G`(3단계)에서 합류한다.
> 3.5단계는 플래그 0건이거나 `refactorAdvisory.enabled: false`면 게이트 없이 3→4로 직결된다(상세: §3).
> 7·8·9단계는 **게이트 충족까지 반복**하며, 직전과 동일한 실패/gap/survivor가 3회 연속(무진전)이면 `partial`로 중단한다(fallback-policy.md #12).
> 8·9단계에서 테스트가 **추가·수정**되면 각 단계 수렴 후 6단계(run-tests)로 **회귀 실행**해 그린을 확인하고(실패 시 7단계 보정 재진입), 최종 `runResult`를 재할당해 10단계에 전달한다 — 10단계가 stale 실행 결과로 판정하는 것을 방지.

---

## 2. Phase E — 환경 세팅 (선(先) 세팅, 후(後) 실행)

```mermaid
flowchart TD
    Start(["전처리 직후 — 0단계 진입 전"]) --> Todo["TodoWrite로 체크리스트 생성<br/>pending → in_progress → completed"]
    Todo --> Detect["각 항목 감지(detect)"]

    Detect --> Auto{"자동 가능 항목?<br/>E2 MCP SDK · E6 JavaParser jar"}
    Auto -- "대화형" --> AskA["AskUserQuestion<br/>'지금 함께 세팅할까요?'"]
    AskA -- "예" --> RunA["pip install -r mcp/requirements.txt<br/>mvn -q -DskipTests package"]
    AskA -- "아니오" --> FailE(["status: failed + remediation"])
    Auto -- "CI/비대화형" --> RunA
    RunA --> Verify["재감지(verify)"]

    Detect --> Assist{"시스템/비결정 항목?<br/>E1 Python · E4 JDK17 · E5 Maven · E7 JDT LS+Java21 · E10 실행JDK↔Mockito"}
    Assist -- "대화형" --> AskB["AskUserQuestion<br/>설치/런타임 경로 안내"]
    Assist -- "CI/비대화형" --> CIstop{"충족됨?"}
    CIstop -- "아니오" --> FailE
    AskB -- "못 갖춤" --> FailE
    AskB -- "갖춤" --> Verify
    CIstop -- "예" --> Verify

    Gate{"필수 E1·E2·E3 + E10 completed?<br/>(E8·E9는 0.5단계 · E4~E7 선택/degrade)"}
    Verify --> Gate
    Gate -- "아니오" --> FailE
    Gate -- "예" --> Ok(["0단계 configure-harness로 진행"])
```

근거: [environment-setup.md](../references/environment-setup.md) (E2 `mcp[cli]>=1.2.0`, E6 `astcli-1.0.0-shaded.jar`,
E7 Eclipse JDT LS Java 21+ 런타임, E10 Mockito/ByteBuddy JDK 24/25 호환).

---

## 3. 3.5단계 — 리팩토링 권고 게이트 + `test_docs/refactoring/`

```mermaid
flowchart TD
    In(["sourceResult (3단계 산출)"]) --> Enabled{"refactorAdvisory.enabled?"}
    Enabled -- "false" --> Skip(["4단계로 직결 (skipped 명시)"])
    Enabled -- "true" --> Judge["refactor-advisor 판정<br/>complexity / testability / efficiency<br/>(공식문서 근거·임계값: refactor-advisory.md §2)"]
    Judge --> Zero{"advisories 0건?"}
    Zero -- "예" --> Skip2(["게이트 생략 — 4단계로 직결"])
    Zero -- "아니오" --> Save["test_docs/refactoring/RA-&lt;id&gt;.md 저장 (decision: pending)<br/>+ refactoring/INDEX.md + 메인 INDEX '리팩토링 권고' 절"]
    Save --> Mode{"실행 모드"}

    Mode -- "대화형" --> Ask["AskUserQuestion<br/>전체 포함(권장) / 일부 제외 / 전체 제외"]
    Ask -- "전체 포함" --> Include["전 대상 decision: included"]
    Ask -- "일부 제외" --> Exclude["후속 입력으로 RA-id 수신<br/>제외분 decision: excluded (파일 보존)"]
    Ask -- "전체 제외" --> AllOut["전 대상 decision: excluded"]
    Exclude --> Include

    Mode -- "CI/비대화형" --> AutoInclude["전 대상 포함 + warnings 기록<br/>(권고 .md는 그대로 작성)"]

    Include --> Filter
    AutoInclude --> Filter["제외 FQCN 필터링한 astResult/sourceResult를 4단계로<br/>_workspace/03c_advisory_gate.json 저장"]
    AllOut --> Empty(["status: partial — '생성 대상 없음(전량 리팩토링 권고)'"])
    Filter --> Next(["4단계 generate-scenarios"])
```

근거: [refactor-advisory.md](../references/refactor-advisory.md) §4, [fallback-policy.md](../references/fallback-policy.md) #19.
권고 `.md`는 포함/제외와 무관하게 **항상 작성**된다 — 게이트는 "테스트 생성 대상 포함 여부"만 결정한다.

---

## 4. 4.5단계 — 시나리오 승인 게이트 + `test_docs/`

```mermaid
flowchart TD
    In(["ScenarioSet (4단계 산출)"]) --> Save["test_docs/scenarios/&lt;id&gt;.md 저장 (approval: pending)<br/>+ test_docs/INDEX.md 갱신"]
    Save --> Mode{"실행 모드"}

    Mode -- "대화형" --> Ask["AskUserQuestion<br/>전체 승인 / 일부 제외·수정 / 재설계 요청"]
    Ask -- "전체 승인" --> Approve["승인분 approval: approved"]
    Ask -- "일부 제외·수정" --> Exclude["제외분 approval: excluded<br/>(파일 보존, 추적성 유지)"]
    Ask -. "재설계 요청" .-> Redesign(["4단계 generate-scenarios 재호출"])
    Exclude --> Approve

    Mode -- "CI/비대화형" --> AutoApprove["전체 자동 승인 + 기록<br/>(승인할 사람 없음)"]

    Approve --> Filter
    AutoApprove --> Filter["approvedScenarios만 5단계로 전달<br/>_workspace/04b_approval.json 저장"]
    Filter --> Empty{"승인 0건?"}
    Empty -- "예" --> Partial(["status: partial — '승인된 시나리오 없음'"])
    Empty -- "아니오" --> Next(["5단계 generate-tests"])
```

근거: [scenario-docs.md](../references/scenario-docs.md) §3, [fallback-policy.md](../references/fallback-policy.md) #15.

---

## 5. 10단계 — 시나리오 적합성 검증 (마지막)

```mermaid
flowchart TD
    In(["승인 시나리오 + 생성 테스트 + 최종 실행결과"]) --> Map["scenarioRef로 매핑<br/>메서드명 sc001_… + javadoc scenarioRef/criteriaRef"]
    Map --> M1{"매핑되는 테스트 메서드 있음?"}
    M1 -- "아니오" --> Missing["verdict: missing"]
    M1 -- "예" --> M2{"매핑 메서드 통과(passed)?"}
    M2 -- "아니오" --> Unsat["verdict: unsatisfied (실패/미실행)"]
    M2 -- "예" --> M3{"// then 단언이 시나리오 then 전부 반영?<br/>thenCovered 충족/전체"}
    M3 -- "아니오 (단언 부족)" --> Unsat
    M3 -- "예" --> Sat["verdict: satisfied"]

    Missing --> Doc
    Unsat --> Doc
    Sat --> Doc["test_docs/scenarios/&lt;id&gt;.md '테스트 코드 매핑'·'검증 결과' 갱신<br/>+ INDEX.md 매핑표 갱신"]
    Doc --> Gate{"unmet (unsatisfied/missing) 존재?"}
    Gate -- "예" --> P{"실행 모드"}
    P -- "대화형" --> Ask["AskUserQuestion<br/>추가 보정 시도 / partial 종료"]
    Ask -. "보정 시도" .-> Rerun(["5→6→(8·9) 부분 재실행"])
    Ask -- "partial 종료" --> Partial(["status: partial — unmet 전량 보고"])
    P -- "CI" --> Partial
    Gate -- "아니오 (전부 satisfied)" --> Ok(["status: ok"])
```

근거: [scenario-docs.md](../references/scenario-docs.md) §4, [fallback-policy.md](../references/fallback-policy.md) #16.

---

## 6. Fallback 의사결정 공통 패턴 (대화형 vs CI)

모든 fallback 지점은 같은 패턴으로 분기한다(SSOT: [fallback-policy.md](../references/fallback-policy.md)).

```mermaid
flowchart LR
    Cond(["fallback 조건 발생"]) --> Mode{"실행 모드"}
    Mode -- "대화형 CLI" --> Ask["AskUserQuestion<br/>(질문/함께 세팅)"]
    Ask --> Proceed(["답에 따라 진행/중단"])
    Mode -- "비대화형 / CI" --> Det{"결정적 환경 세팅 항목?<br/>(pip install · mvn package)"}
    Det -- "예" --> AutoFix["자동 세팅 후 재검증"]
    AutoFix --> OkOrStop(["성공 진행 / 실패 중단"])
    Det -- "아니오 (비결정·런타임 선택)" --> Hard(["하드 중단<br/>status: failed + remediation"])
```

> MCP 서버(stdio)는 비대화형이라 직접 질문하지 못한다 — 조건을 신호(`status:failed`/`requiresConfirmation`/`degraded`/error code)로
> **노출만** 하고, 질문/중단은 이를 소비하는 **스킬·에이전트 계층**이 수행한다(공통규칙 3).

---

## 7. 단계 ↔ 스킬 ↔ 에이전트 ↔ MCP 매핑

| 단계 | 스킬 | 에이전트 | 주 MCP | 산출물 |
|---|---|---|---|---|
| Phase E | configure-harness (Preflight) | — | build-test(detect) | (환경 통과) |
| 0 | configure-harness | — | build-test(`detect_spring_profile`) | `HarnessConfig`, `_workspace/00_*.json` |
| 0.6 | configure-harness(빌드 능력·캐시) | — | build-test(`detect_build_capabilities`·`check_dependency_cache`) | `buildChanges[]`, `_workspace/00b_build_provision.json` |
| 1 | ingest-specs | spec-reviewer | spec-doc | `_workspace/01_*.json` |
| 2 | analyze-ast | ast-structure-analyzer | repo-ast | `_workspace/02_*.json` |
| 3 | analyze-source | source-code-analyzer | repo-ast, (lsp) | `_workspace/03_*.json` |
| 3.5 | refactor-advisory + full-pipeline(게이트) | refactor-advisor | repo-ast, (lsp) | `test_docs/refactoring/*.md`, `03b_refactor_advisory.json`, `03c_advisory_gate.json` |
| 4 | generate-scenarios | scenario-generator | spec-doc, repo-ast | `_workspace/04_scenario_set.json` |
| 4.5 | full-pipeline(승인) | — | — | `test_docs/scenarios/*.md`, `INDEX.md`, `04b_approval.json` |
| 5 | generate-tests | test-code-generator | repo-ast, build-test | `src/test/java/*`, `05_*.json` |
| 6 | run-tests | test-runner | build-test | `06_run_result.json` |
| 7 | repair-tests | test-fixer | all | `07_repair_result.json` |
| 8 | measure-coverage | coverage-closer | build-test(JaCoCo) | `08_coverage_result.json` |
| 9 | mutation-test | mutation-analyst | build-test(PITest) | `09_mutation_result.json` |
| 10 | verify-scenarios | scenario-conformance-verifier | repo-ast, build-test | `test_docs/` 갱신, `10_conformance.json` |

---

## 8. 산출물 위치

```mermaid
flowchart TD
    Root["대상 프로젝트 루트 (projectRoot)"]
    Root --> Src["src/test/java/** — 생성된 테스트 코드"]
    Root --> Docs["test_docs/ — 시나리오 living documentation (영속, 커밋 가능)"]
    Docs --> Index["INDEX.md — 시나리오↔테스트코드↔결과 매핑표 + 리팩토링 권고 요약"]
    Docs --> Scn["scenarios/&lt;SC-ID&gt;.md — 시나리오별 (BDD + 매핑 + 검증결과)"]
    Docs --> Ra["refactoring/RA-&lt;ID&gt;.md + INDEX.md — 리팩토링 권고 (근거·수정법·결정)"]
    Root --> Ws["_workspace/ — 중간 JSON (감사용, ignore 대상)"]
    Ws --> Wsj["00~10_*.json · timing.json · pipeline_result.json"]
```

`test_docs/`는 사람이 읽는 영속 산출물이라 대상 프로젝트에 커밋될 수 있고, `_workspace/`는 운영 중간 산출물이라 ignore 대상이다.

---

## 출처 (사실 확인 2026-06-27)

- Mermaid 공식 flowchart 문법(노드·마름모 의사결정 `{}`·subgraph·방향 `TD/LR`): [Flowcharts Syntax | Mermaid](https://mermaid.ai/open-source/syntax/flowchart.html)
- BDD/Living Documentation 추적성(흐름 설계 근거): [Serenity BDD — Living Documentation](https://serenity-bdd.github.io/docs/reporting/living_documentation), [Cucumber — How does BDD affect traceability](https://cucumber.io/blog/bdd/how-does-bdd-affect-traceability/)
- 단계·정책 정본: 본 저장소 `skills/full-pipeline/SKILL.md`, `references/environment-setup.md`, `references/scenario-docs.md`, `references/fallback-policy.md`
