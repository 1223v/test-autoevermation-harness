# 리팩토링 권고 게이트 (SSOT)

이 문서는 하네스의 **리팩토링 권고 산출물(`test_docs/refactoring/`)·탐지 기준·사용자 결정 게이트(3.5단계)**에 대한
단일 출처(Single Source of Truth)다. `full-pipeline`·`refactor-advisory` 스킬과 `refactor-advisor` 에이전트는 이 문서를 따른다.

설계 배경(웹 검증 2026-07-02): 테스트하기 어렵게 설계된 코드(강결합·숨은 의존·과다 복잡도)에 그대로 테스트를 붙이면
**나쁜 설계를 테스트로 고착**시키고, 복잡도만큼 테스트 경로가 늘어나 취약·과다 테스트를 유발한다
(NIST SP 500-235의 structured testing에서 **순환복잡도 = 검증에 필요한 기본 경로(basis path) 테스트 수**).
따라서 코드 분석(3단계) 직후, 시나리오 생성(4단계) **전에** 문제 코드를 식별해 권고 문서를 남기고
사용자가 "생성 대상 포함/제외"를 결정하는 게이트를 둔다.

---

## 1. 핵심 원칙

1. **권고 `.md`는 항상 작성한다.** 포함/제외 결정과 무관하게, 플래그된 대상 1건당 `test_docs/refactoring/RA-<id>.md`
   1개를 남긴다(침묵 누락 금지). 게이트는 "테스트 생성 대상에 포함할지"만 결정한다.
2. **판정은 공식/1차 문서 근거로만 한다.** 임의 수치·주관적 취향 금지. 각 발견은 아래 §2의 기준·출처에 매핑돼야 한다.
3. **에이전트는 read-only 분석만 한다.** `refactor-advisor`는 `RefactorAdvisoryResult` JSON만 반환하고,
   `.md` 저장·`AskUserQuestion` 게이트·대상 필터링은 `full-pipeline` 오케스트레이터(3.5단계)가 수행한다
   (4.5 시나리오 승인 게이트의 scenario-generator ↔ full-pipeline 분업과 동일).
4. **제외는 삭제가 아니다.** 제외된 대상은 `decision: excluded`로 파일에 보존하고, 4단계 입력에서만 필터링한다(추적성 유지).
   **advisory의 하류 효과는 여기까지다 — 8·9단계 게이트와 무관하다(fallback-policy.md #21).** included 대상은 HIGH advisory라도
   완전한 커버리지·뮤테이션 의무를 지며, advisory를 근거로 coverage-closer/mutation-analyst 루프를 건너뛰는 것은 계약 위반이다.
   "구조적으로 커버 불가"는 해당 에이전트가 루프 수행 후 `remainingGaps[].reason`으로만 판정하고, 스코프 제외는
   `HarnessConfig.coverage.excludes`(사용자 승인)로만 한다.
5. **비대화형·CI 기본값은 "포함+경고"다.** 결정할 사람이 없으므로 전 대상을 생성에 포함하되 권고 `.md`는 그대로 작성한다
   (#15 CI 자동승인과 정합. fallback-policy.md **#19**).
6. **보안 취약점 탐지는 이번 게이트 범위에 포함하지 않는다.** `categories`는 확장 가능한 enum이며 `security`는
   예약만 해 둔다(향후 확장). 보안 정적분석은 별도 도구(SAST) 영역이다.

---

## 2. 탐지 범주·기준 (3종, 공식문서 근거)

에이전트 계층 탐지: `refactor-advisor`가 대상 심볼(FQCN)의 소스를 스코프 한정 `Read`/`Grep`으로 직접 읽어
신호를 계산한다(MCP는 메타 제공만 — repo-ast는 설계상 메서드 바디를 반환하지 않는다).
`sourceResult.testSeams`·`collaborators`(3단계 산출)를 입력 신호로 재사용해 이중 파싱을 피한다.

### 2.1 `complexity` — 순환복잡도 초과

| 항목 | 값 |
|---|---|
| 신호 | 메서드 단위 McCabe 순환복잡도 `CC = 1 + (if·for·while·do·case·catch·&&·\|\|·?:)` 분기 수 |
| 기본 임계 | **CC > 10** 플래그 (`thresholds.cyclomatic`, HarnessConfig로 오버라이드 가능) |
| severity | 11–15 `medium` / **>15 `high`** |

근거 — NIST SP 500-235 *Structured Testing: A Testing Methodology Using the Cyclomatic Complexity Metric*
(<https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf>):
McCabe가 제안한 **한도 10은 유의미한 근거가 축적된 출발점**이며, 15까지의 상향은 "숙련된 인력·정형 설계·코드 워크스루·
포괄적 테스트 계획" 같은 운영상 이점과 **추가 테스트 노력**을 감수할 때만 허용된다. structured testing에서
복잡도는 곧 **기본 경로 테스트 수**이므로, 고복잡도 메서드에 테스트를 먼저 붙이는 것은 경로 폭발을 그대로 떠안는 선택이다 —
분해(메서드 추출·조기 반환·전략 분리) 후 테스트가 원칙.

### 2.2 `testability` — 테스트 저해 설계

| 신호 | 탐지 패턴(예) |
|---|---|
| 생성자가 실질 작업 수행 | 생성자/필드 초기화의 `new 협력객체()`, static 호출, I/O |
| 강결합(숨은 의존) | 메서드 본문의 `new 협력객체()` 직접 생성(주입 없음), `싱글턴.getInstance()` |
| 전역/정적 상태 의존 | mutable `static` 필드 읽기·쓰기, static 유틸에 숨은 상태 |
| 미주입 seam | `LocalDateTime.now()`·`System.currentTimeMillis()`·`new Random()`·`UUID.randomUUID()` 직접 호출 (3단계 `testSeams`와 연동) |
| 협력자 파고들기 | `a.getB().getC().do()` 열차 사고(train wreck) 체인 |

근거:
- **Spring Framework 공식 레퍼런스** — Core > Dependency Injection
  (<https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html>):
  "The Spring team generally advocates constructor injection … ensures that required dependencies are not `null`";
  DI를 쓰면 "your classes become easier to test, particularly when the dependencies are on interfaces or abstract
  base classes, which allow for stub or mock implementations". 또한 **"a large number of constructor arguments is
  a bad code smell, implying that the class likely has too many responsibilities and should be refactored"** —
  생성자 인자 과다(기본 임계 `thresholds.constructorArgs > 7`)도 본 범주 신호로 쓴다.
- **Google Testing Blog — Guide to Writing Testable Code**
  (<https://testing.googleblog.com/2008/11/guide-to-writing-testable-code.html>): 4대 flaw —
  ① Constructor does Real Work(생성자 내 `new`/static 호출), ② Digging into Collaborators(열차 사고 체인),
  ③ Brittle Global State & Singletons("Global state is the enemy of testing"), ④ Class Does Too Much.
- **Mockito 공식 javadoc** (<https://javadoc.io/doc/org.mockito/mockito-core/latest/org/mockito/Mockito.html>):
  §39(final 타입 mock — inline mock maker는 **5.0.0부터 기본**), §48(static mock — **현재 스레드에 한정**되고
  try-with-resources로 스코프를 닫아야 함). 즉 static/final 의존은 mock이 "가능"해도 스코프·정리 제약이 크고,
  **Boot 2.x 프로파일(구 Mockito 2.x/3.x)에서는 별도 `mockito-inline` 없이는 불가** — 주입 가능한 seam으로의
  리팩토링(예: `Clock` 주입)이 우선이다.

### 2.3 `efficiency` — 비효율

| 신호 | 탐지 패턴(예) |
|---|---|
| N+1 쿼리 | 루프(`for`/`stream().map`) 내부의 repository/EntityManager 조회 호출 |
| 루프 내 반복 비용 | 루프 내 동일 인자 재계산·불필요 객체 할당·루프 내 원격 호출(HTTP) |
| eager 남용 | 연관관계 `FetchType.EAGER` 명시(+ 쿼리에서 미사용) |

근거 — **Hibernate ORM 공식 User Guide, Fetching 장**
(<https://docs.hibernate.org/orm/5.2/userguide/html_single/chapters/fetching/Fetching.html>,
현행판: <https://docs.jboss.org/hibernate/orm/6.6/userguide/html_single/Hibernate_User_Guide.html#fetching>):
행별 추가 SELECT가 발생하는 패턴을 **"the strategy generally termed N+1"**로 명명하고,
"you should prefer LAZY associations"를 권고하며, 해법으로 **JOIN FETCH·entity graph·`@BatchSize`**를 제시한다
("most of the time, a DTO projection or a JOIN FETCH is a much better alternative"). 루프 내 쿼리는 이 패턴의
애플리케이션 코드 판이므로 동일 근거로 플래그한다.

### 2.4 severity 산정 규칙

- `high`: CC > 15, 또는 **2개 이상 범주** 동시 플래그, 또는 N+1이 트랜잭션 경계 안에서 확인됨.
- `medium`: 단일 범주 + 임계 초과(CC 11–15, 루프 내 쿼리 1곳, 생성자 실질 작업 등).
- `low`: 경계 신호(임계 근접, 정황상 의심이나 단정 불가) — 권고만, 기본 포함 권장.

허위 양성 억제: 테스트 코드·`equals/hashCode/toString`·generated 코드(`build/`·`target/`·`generated/`)는 제외.
static 호출 중 순수 함수 유틸(`Math.*`, `Collections.*`, `Objects.*`, 문자열 유틸)은 플래그하지 않는다.

---

## 3. `test_docs/refactoring/` 디렉터리 구조

```
<projectRoot>/test_docs/refactoring/
├── INDEX.md                  # 권고 요약 표(대상↔범주↔severity↔결정↔생성여부)
└── RA-001.md ...             # 권고 1건 = 파일 1개
```

규칙:
- 파일명은 advisory `id`(`RA-001.md`). 안정적 ID라 재실행 시 같은 파일을 갱신(전량 재작성 금지, 변경분만).
- `test_docs/`는 사람이 읽는 영속 산출물 — 대상 프로젝트에 커밋 가능(`_workspace/`와 달리 ignore 대상 아님).
- 소스 원문·민감정보는 기록하지 않는다(경로·라인·지표·발췌 요지 수준만). scenario-docs.md §2와 동일 규약.
- 메인 `test_docs/INDEX.md`에 "## 리팩토링 권고" 요약 절(건수 + `refactoring/INDEX.md` 링크)을 추가한다.

### 3.1 권고 파일 템플릿 (`refactoring/RA-<id>.md`)

```markdown
---
advisoryId: RA-001
target: com.example.order.OrderService#createOrder
categories: [complexity, testability]
severity: high
decision: pending          # pending | included | excluded
decidedAt: —
---

# RA-001 — OrderService#createOrder 리팩토링 권고

## 발견
| 신호 | 값 | 임계 | 근거 위치 |
|---|---|---|---|
| cyclomatic | 14 | 10 | `OrderService.java:42-118` |
| unmockable-seam | LocalDateTime.now() 직접 호출 | — | `OrderService.java:57` |

## 왜 문제인가 (근거)
- 순환복잡도 14 > 10: NIST SP 500-235는 한도 10을 출발점으로 제시하며, 초과분은 추가 테스트 노력을 요구한다.
  <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf>
- `now()` 직접 호출: 시간이 주입되지 않아 결정적 테스트가 불가하다. static mock(Mockito §48)은 스레드 한정 +
  try-with-resources 제약이 있고 Boot 2.x 프로파일에선 별도 mockito-inline 없이는 불가.
  <https://javadoc.io/doc/org.mockito/mockito-core/latest/org/mockito/Mockito.html>

## 왜 지금 테스트 작성이 부적절/위험한가
- structured testing 기준(NIST SP 500-235)에서 복잡도 = 필요한 기본 경로 테스트 수. CC 14는 최소 14개 경로
  테스트를 요구하며, 분기 구조가 바뀌면 대부분 깨진다 — **설계 결함이 테스트로 고착**된다.
- 미주입 clock 탓에 시간 의존 단언이 비결정적(flaky)이거나, static mock으로 우회하면 리팩토링 유인이 사라진다.

## 권장 리팩토링
1. 검증/할인/저장 단계를 메서드 추출로 분리해 각 CC ≤ 10으로 낮춘다 (NIST SP 500-235: 분해 후 테스트).
2. `java.time.Clock`을 생성자 주입하고 `now(clock)`으로 전환한다 (Spring 공식: 생성자 주입 권고 —
   <https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html>).

## 결정
- decision: pending        <!-- 게이트 후 included/excluded + 사유·시각 기재 -->

## 추적성
- 포함 시 연결 시나리오/테스트: —   <!-- 4단계 이후 SC-id, 테스트 메서드 기재 -->
- 인덱스: [refactoring/INDEX.md](INDEX.md) · 메인: [../INDEX.md](../INDEX.md)
```

미채움 섹션은 해당 단계 전까지 `<!-- 대기 -->`로 둔다.

### 3.2 인덱스 템플릿 (`refactoring/INDEX.md`)

```markdown
# 리팩토링 권고 인덱스

> 생성: 2026-07-02 · 프로젝트: `/path/to/project` · 하네스 v0.9.0

## 요약
- 권고: 3 (포함 2 / 제외 1) · 게이트 모드: interactive

| 권고 | 대상 | 범주 | severity | 결정 | 테스트 생성 |
|---|---|---|---|---|---|
| [RA-001](RA-001.md) | OrderService#createOrder | complexity, testability | high | ✅ 포함 | 진행 |
| [RA-002](RA-002.md) | ReportService#buildAll | efficiency | medium | ⛔ 제외 | 안 함 |

범례: 결정 ✅포함(권고 기록 + 테스트 생성) / ⛔제외(권고 기록만)
```

---

## 4. 결정 게이트 (3.5단계 — fallback-policy.md #19)

`refactor-advisor`가 `RefactorAdvisoryResult`를 반환한 직후(플래그 0건이면 게이트 생략, 3→4 직결):

1. **선(先) 기록**: 각 advisory를 `test_docs/refactoring/RA-<id>.md`(`decision: pending`)로 쓰고
   `refactoring/INDEX.md`와 메인 `test_docs/INDEX.md` 요약 절을 갱신한다.
2. **결정 게이트**:
   - **대화형**: 권고 요약(대상·범주·severity 표)을 제시하고 `AskUserQuestion`으로 묻는다 —
     선택지 `전체 포함(권장)` / `일부 제외` / `전체 제외` (4.5 게이트 #15의 3옵션 패턴 미러 —
     AskUserQuestion은 질문당 옵션 최대 4개이므로 대상별 나열 대신 고정 옵션 + 후속 입력을 쓴다).
     - `일부 제외`: 후속 질문 또는 자유 입력으로 제외할 `RA-id`를 받는다. 제외분은 `decision: excluded`.
   - **비대화형·CI**: **전 대상 포함 + `warnings` 기록**(권고 `.md`는 그대로 작성). 침묵 누락 금지.
3. **반영**: 포함분 `decision: included`, 제외분 `decision: excluded`(+ `decidedAt`, 사유)로 frontmatter를 갱신한다.
   결과를 `_workspace/03c_advisory_gate.json`에 저장한다.
4. **필터**: 제외 대상 FQCN을 뺀 `includedTargets` 기준으로 `astResult.testTargets`·`sourceResult`를 필터링해
   4단계(generate-scenarios) 입력으로 넘긴다. **전 대상 제외로 포함이 0건이면** 4.5의 "승인 0건"에 준해
   `status: "partial"` + "생성 대상 없음(전량 리팩토링 권고)" 보고 후 중단한다.

포함된 대상의 시나리오·테스트가 생성되면(4~5단계 이후) 해당 `RA-*.md`의 "추적성" 절에 SC-id·테스트 메서드를 기록한다.

에이전트 판정이 `failed`면 **경고 후 전 대상 포함으로 진행**한다(`warnings: REFACTOR_ADVISORY_FAILED`) —
권고는 보조 게이트이므로 파이프라인을 차단하지 않는다(2단계 AST 실패의 하드 중단과 다름).

---

## 5. HarnessConfig 오버라이드

`HarnessConfig`(정본: configure-harness SKILL.md 「5단계」)의 선택 필드로 제어한다:

```json
"refactorAdvisory": {
  "enabled": true,
  "thresholds": { "cyclomatic": 10, "constructorArgs": 7 }
}
```

- `enabled: false`면 3.5단계 전체를 건너뛴다(3→4 직결, 권고 `.md`도 만들지 않음 — 보고서에 skipped 명시).
- `thresholds` 미지정 시 본 문서 §2의 기본값. 임계 상향은 NIST SP 500-235의 조건(추가 테스트 노력 감수)을
  이해한 사용자의 명시적 선택으로 본다.
- 인터뷰 항목은 추가하지 않는다(비침습 기본값) — `HarnessRequest`로만 오버라이드.

---

## 6. `_workspace/`·부분 재실행 연계

- `03_source_seams.json`(3단계) → `03b_refactor_advisory.json`(에이전트 산출) → `03c_advisory_gate.json`(결정)
  → 4단계 입력 필터. 상세: orchestration-detail.md §2·§3.
- 부분 재실행 "리팩토링 권고만 다시"는 3.5만 재실행하고 01~03을 재사용한다. 2·3단계가 재실행되는 요청
  ("이 패키지만 다시" 등)은 3.5도 함께 재실행한다(대상 집합이 바뀌므로).
- `test_docs/refactoring/`은 영속 산출물, `_workspace/*.json`은 감사용 중간 산출물(서로 다른 위치).
