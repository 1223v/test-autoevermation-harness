# Fallback 정책 (SSOT)

이 문서는 하네스의 **모든 fallback 지점의 처리 정책**에 대한 단일 출처(Single Source of Truth)다.
모든 에이전트·스킬·MCP 서버는 fallback 상황에서 이 표를 따른다. 사용자가 직접 선택한 정책이며,
임의로 침묵 degrade하지 않는다.

> **선(先) 세팅 원칙**: 환경·역량·버전 감지 항목(#1·#2·#3·#4·#5·#6·#20)은 파이프라인 도중에 "마주치는" 것이 아니라
> 시작 시점의 **Phase E 환경 세팅 체크리스트**([environment-setup.md](./environment-setup.md))에서 **선제적으로 처리**한다.
> 자동으로 고칠 수 있는 항목은 **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / 비대화형·CI=자동 세팅**. 아래 표는 그 처리 결과를 정의한다.

## 공통 규칙 (전 항목 공통)

1. **대화형 CLI**: fallback 조건이 발생하면 `AskUserQuestion`으로 사용자에게 묻고, 답에 따라 진행/중단한다.
2. **비대화형 / CI(`claude -p`)**: `AskUserQuestion`이 불가능하다. **결정적 환경 세팅 항목**(Phase E의 E2 MCP SDK
   `pip install`, E6 JavaParser jar `./mvnw package`, E7 JDT LS `setup_jdtls.py`처럼 고정 명령으로 고칠 수 있는 것)은 **자동 세팅**한 뒤 재검증한다.
   자동 세팅이 실패하거나 **비결정적 항목**(버전·프로파일·미지정 입력처럼 사람이 골라야 하는 것)은 **하드 중단**한다 —
   `status: "failed"`, `errors`에 조건과 **remediation(해결 명령)**을 명시하고 비정상 종료(exit≠0). **침묵 degrade·임의 기본값 금지.**
   사용자는 `HarnessRequest`에 값을 미리 채워 중단을 피할 수 있다.
3. **MCP 서버는 비대화형**(stdio)이므로 직접 질문할 수 없다. MCP는 조건을 신호(`status:failed` /
   `requiresConfirmation:true` / `degraded:true` / 명시적 error code)로 **노출만** 하고, 질문/중단은 이를
   소비하는 **에이전트·스킬 계층**이 수행한다.
4. fallback으로 인한 누락은 **임의 제외·무시 없이** 보고서에 반드시 명시한다.
5. **Phase E의 `AskUserQuestion` 선택지에 "degrade로 계속" 류 옵션을 두지 않는다.** 허용 선택지는 "지금 세팅"과
   "중단"뿐이다 — 환경 항목(E3b·E4·E5·E6·E7 포함)은 전부 필수이며, 미충족 상태로 파이프라인에 진입하는 경로는 없다.

## 정책 표

| # | Fallback 지점 | 정책 | 신호/구현 위치 |
|---|---|---|---|
| 1 | **MCP Python SDK(`mcp[cli]`) 미설치** | **Phase E·E2에서 선세팅.** 대화형: AskUserQuestion "함께 세팅할까요?" → 예: `python3 -m pip install -r mcp/requirements.txt` 후 재검증 / 아니오: 중단. **CI: 자동 설치** 후 재검증, 실패 시 중단 | `configure-harness` Phase E; [environment-setup.md](./environment-setup.md) E2 |
| 2 | **JavaParser jar / JDK 미가용** | **필수 — degrade 없음.** Phase E·E6에서 자동 빌드: 대화형=`AskUserQuestion`("예 — jar 빌드(`./mvnw package`)" / "아니오 — 중단"만, 정규식 degrade 선택지 없음). CI=자동 빌드(`cd mcp/javaparser-cli && ./mvnw -q -DskipTests package`), 실패 시 **하드 중단**(`JAVAPARSER_REQUIRED`). `REPO_AST_JAVAPARSER_JAR` 사전 지정도 가능. `.mcp.json`이 기본 `REPO_AST_REQUIRE_JAVAPARSER=1`을 설정하므로 repo-ast는 jar 미가용 시 항상 `status:"failed"`를 반환한다(정규식 fallback은 플러그인 배포에서 비활성 — 서버 스크립트를 단독 사용하는 경우에만 코드 기본값으로 남아 있음) | `repo-ast`(`status:failed`+`JAVAPARSER_REQUIRED`); `configure-harness` Phase E·E6; `ast-structure-analyzer` |
| 3 | **JDT LS(LSP) 미가용** | **필수 — degrade 없음.** Phase E·E7에서 `scripts/setup_jdtls.py`(PATH → brew → tarball → `${CLAUDE_PLUGIN_DATA}/jdtls`)로 자동 설치하고 Java 21+를 요구한다. 설치/검증 실패 시 **하드 중단**(AST-only degrade로 진행하지 않음). `lspAvailable:false` 상태로는 파이프라인 진행을 금지한다. 대화형: 설치 실패 시 중단. CI: 동일하게 하드 중단 | `configure-harness` Phase E·E7(필수); `source-code-analyzer`, `analyze-source` |
| 4 | **Boot 버전 미감지** | **0.5단계(E9)에서 확정.** 대화형: AskUserQuestion으로 Boot major/프로파일 질문, 충족 안 되면 중단. CI: 중단(`HarnessRequest.springVersion` 명시) | `build-test` `detect_spring_profile` `degraded:true`+`INTERVIEW_REQUIRED`; `configure-harness` 0.5단계 |
| 5 | **gradle/maven 빌드도구 미감지** | **0.5단계(E8)에서 확정.** 대화형: AskUserQuestion으로 빌드도구 질문 후 진행. CI: 중단(`HarnessRequest.buildTool` 명시) | `build-test` `detect_build_tool` `status:partial`+`BUILD_TOOL_UNDETECTED`; `configure-harness`/`test-runner` |
| 6 | **namespace(javax/jakarta)·JUnit 엔진 자동 override** | **0.5단계(E9)에서 확정. 자동 적용 금지.** 빌드파일 값과 소스/기존테스트 값이 충돌하면 대화형=AskUserQuestion으로 어느 쪽을 따를지 확인 후 적용 / CI=중단 | `build-test` `detect_spring_profile` `requiresConfirmation:true`+`conflicts[]`; `configure-harness` |
| 7 | **PITest 버전 폴백/graceful skip** | AskUserQuestion으로 "1.7.4 폴백 / 뮤테이션 skip / 중단" 중 선택. CI: 중단 | `mutation-test`, `mutation-analyst` |
| 8 | **test-runner 대상 클래스 미지정** | AskUserQuestion으로 "대상 지정 / 전체 실행" 확인. CI: 중단 | `test-runner`, `run-tests` |
| 9 | **test-runner XML 리포트 미생성** | AskUserQuestion으로 "stdout 파싱 진행 / 중단" 확인. CI: 중단 | `test-runner` |
| 10 | **spec-doc 읽기불가(권한/암호PDF)** | AskUserQuestion으로 "나머지로 계속 / 중단" 확인. CI: 중단 | `spec-reviewer`, `ingest-specs` |
| 11 | **에이전트 불가항목 건너뛰기** (시그니처 미해석·매핑불가 criteria·equivalent mutant·원인분류불가·패치적용실패) | AskUserQuestion으로 "건너뛰고 보고 / 중단" 확인. CI: 중단 | `coverage-closer`, `scenario-generator`, `mutation-analyst`, `test-fixer`, `repair-tests` |
| 12 | **full-pipeline 단계 실패 / 게이트 미수렴** | **성공까지 재시도.** 단, 직전과 **동일한 실패·동일 gap/survivor가 3회 연속**(무진전)이면 "무진전"으로 보고하고 중단 | `full-pipeline`, `orchestration-detail` |
| 13 | **입력 필드 미지정**(projectRoot/buildTool/javaVersion/springVersion 등) | **전부 AskUserQuestion으로 질문.** auto-detect/기본값으로 자동 채우지 않음. CI: 중단 | `configure-harness`, `full-pipeline` |
| 14 | (보안 기본값 — 유지) 네트워크 기본 OFF, `REPO_AST_ALLOW_ROOT` 미설정 시 cwd 한정, allowlist 밖 경로 스킵 | **현행 유지**(degradation이 아닌 보안 자세) | `build-test`, `repo-ast` |
| 15 | **시나리오 승인 게이트**(4.5단계) | 시나리오는 사용자 승인을 받는다. **대화형: `AskUserQuestion`**(전체 승인/일부 제외·수정/재설계) → 승인분만 생성으로 진행. **CI/비대화형: 승인할 사람이 없으므로 자동 승인** 후 `test_docs/`에 기록(감사 추적). 승인은 본질적으로 대화형 전용 | `full-pipeline` 4.5단계; [scenario-docs.md](./scenario-docs.md) §3 |
| 16 | **시나리오 적합성 미충족**(10단계 — unsatisfied/missing) | 통과한 테스트가 시나리오 given/when/then을 만족하는지 검증(target 호출은 repo-ast `methodCalls` 기계 대조). `unmet`이 있으면 **10.5단계 적합성 자동 보정 루프**를 대화형·CI 동일하게 자동 수행: unsatisfied→`test-fixer` 모드 B(`SCENARIO_NONCONFORMANT` 최소 diff), missing→`test-code-generator` 부분 재생성 → 6단계 재실행 → 10단계 재검증. **최대 3라운드, 직전 라운드와 동일 unmet 집합이면 즉시 무진전 중단** — #12(무제한, 결정적 신호 전제)의 **명시적 예외**(적합성 판정은 일부 LLM 판단이라 진동 위험). 소진 후 잔여: 대화형=`AskUserQuestion`("수동 보정 계속/partial 종료"), CI=`status:"partial"` + 잔여 전량 보고. 임의 제외 금지 | `full-pipeline` 10.5단계; `verify-scenarios`; `scenario-conformance-verifier`; `test-fixer`(모드 B); [scenario-docs.md](./scenario-docs.md) §4 |
| 17 | **대상 빌드 능력 미비**(JaCoCo XML/PITest 플러그인 미적용 — 8·9단계 선행) | **0.6단계(E11)에서 detect→approve→inject.** JaCoCo XML 기본 OFF·PITest 태스크 부재로 커버리지/뮤테이션이 깨짐. 대화형=`AskUserQuestion` 승인 후 최소 스니펫 주입(`buildChanges[]` 기록)·재감지 / CI=자동 주입 금지, 누락+스니펫 remediation 중단. 침묵 주입 금지 | `build-test` `detect_build_capabilities` `missing[]`+`proposedChanges[]`; `configure-harness` 0.6단계; [build-provisioning.md](./build-provisioning.md) §1 |
| 18 | **콜드 의존성 캐시**(첫 오프라인 실행 의존성/플러그인 해석 실패 — 6단계 선행) | **0.6단계(E12)에서 점검.** Gradle `--offline`은 미캐시 모듈 시 빌드 실패. 대화형=`AskUserQuestion` 승인 후 `run_targeted_tests(online=True)` 1회 프라이밍(또는 Maven `dependency:go-offline`)→이후 오프라인 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·사전 워밍업 안내, 미충족 시 첫 실행 실패를 partial 보고. 상시 온라인 아님(#14 유지) | `build-test` `check_dependency_cache` `primed:false`; `run_targeted_tests(online=True)`; [build-provisioning.md](./build-provisioning.md) §2 |
| 19 | **리팩토링 권고 게이트**(3.5단계) | 테스트 부적합 코드(복잡도·비효율·테스트 저해)가 플래그되면 권고 `.md`(`test_docs/refactoring/RA-*.md`)를 **항상 작성**한 뒤 생성 대상 포함 여부를 결정한다. **대화형: `AskUserQuestion`**(전체 포함/일부 제외/전체 제외) → 포함분만 4단계로. **CI/비대화형: 전 대상 포함+경고**(#15 자동승인과 정합 — 권고 기록만 남김). 임의 침묵 누락 금지. 전 대상 제외 시 `partial` 중단. 에이전트 판정 실패 시 경고 후 전 대상 포함으로 진행(보조 게이트 — 파이프라인 차단 안 함) | `full-pipeline` 3.5단계; `refactor-advisor`; [refactor-advisory.md](./refactor-advisory.md) §4 |
| 20 | **MCP 서버 연결 실패** | **필수 — degrade·대체 없음.** Phase E·E3b에서 `repo-ast-mcp.health`·`spec-doc-mcp.health`·`build-test-mcp.health` 실제 호출로 라이브 연결을 검증하고, 파이프라인 도중에도 MCP 도구 호출이 실패(도구 미노출/연결 끊김)하면 즉시 **하드 중단**한다. **Grep/Read/직접 파싱으로 대체하는 것을 금지**한다. remediation: ① 플러그인 활성화 확인 → ② `node <pluginRoot>/mcp/launch.cjs --ensure-only` 수동 실행 → ③ `/reload-plugins` 또는 Claude Code 재시작 → ④ SessionStart 훅 stderr 확인. 대화형·CI 동일하게 하드 중단 | `configure-harness` Phase E·E3b; 전 스킬·에이전트의 MCP 도구 호출 지점 |
| 21 | **게이트 산출물 유효성 + advisory 비면제**(8·9단계) | **RA advisory(리팩토링 권고)는 8·9단계 게이트의 면제·스킵 사유가 아니다** — 3.5단계에서 included된 대상은 완전한 커버리지·뮤테이션 의무를 진다(#19는 4단계 입력 필터링에만 관여). "구조적으로 커버 불가" 판단은 오케스트레이터 권한 밖 — coverage-closer/mutation-analyst가 **루프를 실제 수행한 뒤** `remainingGaps[].reason`/`survivingMutants[]`로만 성립하며, 스코프 제외는 `HarnessConfig.coverage.excludes`(사용자 승인)로만 가능하다(JaCoCo `classDirectories` excludes·PIT `excludedClasses`와 동일한 선언적 모델). **무효 조건**: `08_coverage_result.json`이 `status: ok\|partial`인데 `gatePassed:false` ∧ (`iterations<1` ∨ `remainingGaps` 빈 배열), 또는 `09_mutation_result.json`이 `thresholdMet:false` ∧ (`iterations<1` ∨ `survivingMutants` 빈 배열)이면 **게이트 미수행 산출물로 무효** — 해당 단계를 다시 실행해야 하며 다음 단계 진행 금지(`status:"failed"`+`errors[]`는 도구 고장 경로로 예외). `scripts/guard-gate-artifacts.py` 훅이 무효 산출물 Write를 기계적으로 차단한다 | `full-pipeline` 8·9단계; `measure-coverage`; `mutation-test`; [refactor-advisory.md](./refactor-advisory.md); `scripts/guard-gate-artifacts.py` |

> **Phase E 추가 환경 항목**(번호 없는 세팅 점검, 정본: [environment-setup.md](./environment-setup.md)):
> E1 Python 3.10+ · E4 **JDK 21+**(jar 빌드·JDT LS 구동 공통, 필수) · E5 Maven 3.6.3+(또는 동봉 `mvnw` — 시스템 Maven 불필요) · **E10 테스트 실행 JDK↔Mockito 호환**
> (E3b MCP 라이브 연결 검증은 #20, E6 JavaParser jar는 #2, E7 JDT LS는 #3에서 정의)
> (JDK 24/25 + inline mock-maker는 Mockito 5.16+/ByteBuddy 1.17+ 또는 `-Dnet.bytebuddy.experimental=true` 필요, 아니면 17/21 LTS 권장).
> 모두 Phase E에서 선점검 — 대화형=함께 세팅/안내, CI=결정적 항목 자동·비결정적 항목 중단.

## 재시도 경계 상세 (#12)

- repair-tests → run-tests, coverage-closer → measure-coverage, mutation 강화 루프를 **게이트 충족까지 반복**한다.
- **무진전 판정**: 직전 반복과 비교해 (a) 동일한 실패 시그니처, 또는 (b) 동일한 미커버 라인/브랜치 집합, 또는
  (c) 동일한 survivor mutant 집합이 **3회 연속**이면 무진전으로 간주.
- 무진전 시: `status: "partial"` + 잔여 실패/gap/survivor를 **전량 보고**하고 중단(무한 루프 방지). 임의 제외 금지.
- 진전이 있는 한(실패 수·gap·survivor가 줄어드는 한) 횟수 상한 없이 계속 재시도한다.

## 비대화형 감지

`claude -p`/CI 여부는 `configure-harness`의 `skipInterview`/실행 컨텍스트로 판단한다. 비대화형에서:
- **결정적 환경 세팅 항목**(Phase E·E2/E6/E7: `pip install`·`./mvnw package`·`setup_jdtls.py`)은 질문 대신 **자동 세팅** 후 재검증한다. 자동 세팅 실패 시 하드 중단(#2·#3·#20).
- 그 외 "AskUserQuestion" 항목(비결정적 데이터·런타임 선택)은 **하드 중단 + remediation 안내**로 대체된다(침묵 진행 아님).

자세한 입력 사전공급은 `HarnessRequest`로 한다.
