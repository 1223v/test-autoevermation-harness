# 환경 세팅 체크리스트 (Preflight SSOT)

이 문서는 하네스를 돌리기 **전에** 미리 끝내야 하는 **환경 세팅의 단일 출처(SSOT)**다.
fallback은 파이프라인 도중에 "마주치는" 것이 아니라, 여기서 **선제적으로 세팅**해 제거한다.

> 정책 연계: 런타임 의사결정(스펙 읽기불가·건너뛰기 등)은 [fallback-policy.md](./fallback-policy.md)를 따른다.
> 이 문서는 그중 **환경·역량·버전 감지** 항목(#1·#2·#3·#4·#5·#6 + 테스트 실행 JDK)을 **시작 시점에 일괄 처리**하는 절차다.

## 핵심 원칙

1. **선(先) 세팅, 후(後) 실행.** `full-pipeline`/`configure-harness`는 0단계 진입 전에 이 체크리스트를 **TODO 리스트로 만들고 전부 통과**시킨다. 통과 못한 항목이 있으면 파이프라인을 시작하지 않는다.
2. **함께 세팅 (대화형).** 자동으로 고칠 수 있는 항목은 **항목별로** `AskUserQuestion("지금 함께 세팅할까요?")`로 묻고, "예"면 그 자리에서 설치/빌드 → 재검증 → 체크. 침묵 진행·임의 degrade 금지.
3. **항상 자동 세팅 (비대화형/CI).** `claude -p`/CI에는 질문할 수 없으므로 **결정적 세팅 항목**(pip 설치·jar 빌드 등 고정 명령으로 고칠 수 있는 것)은 **자동 수행**한다. 자동 수행이 실패하거나 **비결정적 항목**(버전 미감지·프로파일 충돌처럼 사람이 골라야 하는 것)은 `status:"failed"` + remediation으로 **하드 중단**한다.
4. **TODO 가시화.** 각 항목을 TodoWrite 항목으로 만들어 `pending → in_progress → completed`로 체크해 나간다. 사용자/로그에 진척이 보이게 한다.
5. **검증 후 체크.** 세팅 액션 뒤에는 반드시 **재감지**해서 통과를 확인한 뒤에만 completed로 표시한다.

---

## 체크리스트 (TODO 항목)

각 항목: **감지(detect) → (미충족 시) 세팅 → 검증(verify)**. `auto`=결정적 자동 세팅 가능, `assist`=사용자와 함께/안내 필요.

| # | 항목 | 감지 | 세팅 종류 | 대화형 동작 | CI 동작 | 연계 |
|---|---|---|---|---|---|---|
| E1 | **Python 3.10+** | `python3 -c "import sys;assert sys.version_info>=(3,10)"` | assist | 미충족 시 AskUserQuestion으로 설치 경로 안내(macOS `brew install python` / Ubuntu·Debian `apt install python3 python3-venv python3-pip` / pyenv). 없으면 중단 | 하드 중단 + remediation | MCP 런타임 |
| E2 | **MCP Python SDK** (`mcp[cli]>=1.2.0`) | `python3 -c "import mcp"` 성공 **또는** bootstrap venv marker 존재 | auto | **자동**(v0.12.0+): `python3 <pluginRoot>/mcp/bootstrap.py --ensure-only` — `${CLAUDE_PLUGIN_DATA}/venv`에 설치, 시스템 python 비오염. 실패 시에만 `AskUserQuestion` → pip 수동 폴백 | **자동** bootstrap 동일, 실패 시 중단 + pip 폴백 remediation | policy #1 |
| E3 | **MCP 서버 3종 등록** (repo-ast·spec-doc·build-test) | `.mcp.json` 존재 + 각 서버 import 가능(`python3 mcp/<server>.py --help` 또는 모듈 로드) | auto | 누락 서버를 `.mcp.json`에 맞춰 점검, import 실패는 E2로 귀결. 재로딩 안내 | 자동 점검, import 실패면 중단 | `.mcp.json` |
| E4 | **JDK 17+** (jar 빌드·일반) | `java -version` ≥ 17 | assist | AskUserQuestion으로 설치/`JAVA_HOME` 지정 안내(sdkman/brew). 없으면 중단 | 하드 중단 + remediation | jar/E6 |
| E5 | **Maven 3.6.3+** (jar 빌드용) | `mvn -version` ≥ 3.6.3 | assist | jar가 이미 있으면 생략 가능. 없고 빌드 필요하면 설치 안내 | jar 없으면 중단(빌드 불가) | E6 |
| E6 | **JavaParser CLI jar** (권장) | `REPO_AST_JAVAPARSER_JAR` 또는 `mcp/javaparser-cli/target/*-shaded.jar` 존재 | auto(best-effort) | `AskUserQuestion("jar 빌드할까요?")` → 예: `(cd mcp/javaparser-cli && mvn -q -DskipTests package)` → `target/astcli-1.0.0-shaded.jar`. 미빌드 시 **정규식 degrade(경고)** | **자동** 동일 명령 빌드, 실패 시 degrade(중단 아님) | policy #2 (기본 degrade; `REPO_AST_REQUIRE_JAVAPARSER=1`은 opt-in 하드실패) |
| E7 | **JDT LS + Java 21+ 런타임** (선택) | `jdtls`(PATH) + `.lsp.json` + Java 21+ on `JAVA_HOME`/PATH | optional | `AskUserQuestion`으로 jdtls 설치·Java 21+ 지정 안내(선택). 미가용이면 AST-only degrade로 진행(중단 안 함) | 미가용이면 AST-only degrade(경고, 중단 안 함) | policy #3 |
| E8 | **빌드 도구**(gradle/maven) | `build-test-mcp.detect_build_tool(root)` | data | `BUILD_TOOL_UNDETECTED`면 `AskUserQuestion("gradle? maven?")` | 미감지면 중단(`HarnessRequest.buildTool` 명시 요청) | policy #5 |
| E9 | **Spring Boot 버전/프로파일** | `build-test-mcp.detect_spring_profile(root)` | data | `interviewRequired`면 Boot major AskUserQuestion(#4); `requiresConfirmation`면 충돌 확정(#6). 가정 금지 | 미감지/충돌이면 중단(`HarnessRequest.springVersion` 명시) | policy #4·#6 |
| E10 | **테스트 실행 JDK ↔ Mockito 호환** | 실행 JDK major vs Mockito/ByteBuddy 지원 범위 | assist | JDK 24/25에서 inline mock-maker 미지원 위험이면 `AskUserQuestion`: "① 테스트 실행 JDK를 17/21 LTS로 / ② Mockito 5.16+(ByteBuddy 1.17+)로 / ③ `-Dnet.bytebuddy.experimental=true`" | 위험이면 자동 보정 불가 → 중단(remediation 안내) | RESEARCH_NOTES §5, ByteBuddy |
| E11 | **대상 빌드 능력**(JaCoCo XML·PITest 플러그인) | `build-test.detect_build_capabilities(root, junitEngine)` → `missing[]` | data(approve→inject) | 누락 시 `AskUserQuestion("빌드 파일에 주입할까요?")` → 예: `proposedChanges[]` 최소 주입(`buildChanges[]` 기록)→재감지 / 아니오: 해당 단계 skipped 보고 | 자동 주입 금지 → 누락+스니펫 remediation 중단 | policy #17, [build-provisioning.md](./build-provisioning.md) §1 |
| E12 | **의존성 캐시 프라이밍**(콜드 캐시 첫 실행) | `build-test.check_dependency_cache(buildTool, root)` → `primed` | data(approve→prime) | `primed:false`/신규 플러그인이면 `AskUserQuestion("1회 온라인 프라이밍?")` → 예: `run_targeted_tests(online=True)` 1회(또는 Maven `dependency:go-offline`)→이후 오프라인 | 자동 온라인 금지 → `BUILD_TEST_ALLOW_NETWORK=1` 옵트인·사전 워밍업 안내 | policy #18, [build-provisioning.md](./build-provisioning.md) §2 |

E8·E9·E10·E11·E12는 **데이터 감지**라 "자동 빌드"로는 못 고친다 — 대화형은 질문(E11·E12는 승인 후 함께 세팅), CI는 `HarnessRequest`에 사전 지정/사전 워밍업(없으면 중단). E11·E12는 **0.5단계(프로파일 확정) 직후 0.6단계에서 6단계 run-tests 이전에** 처리한다 — JaCoCo 에이전트는 `test` 실행 중 attach되므로 빌드 능력이 먼저 갖춰져야 한다.

---

## 세팅 명령 레퍼런스 (사실 확인됨)

```bash
# E2: MCP Python SDK (Python 3.10+) — v0.12.0+ 자동(권장): 플러그인 venv에 설치
python3 "<pluginRoot>/mcp/bootstrap.py" --ensure-only   # → ${CLAUDE_PLUGIN_DATA}/venv에 mcp[cli]>=1.2.0
#   수동 폴백(오프라인/venv 불가 환경): .mcp.json이 실행하는 동일 python3에 설치
python3 -m pip install -r mcp/requirements.txt          # (which python3 로 인터프리터 확인)

# E6: JavaParser CLI jar (JDK 17+, Maven 3.6.3+)
cd mcp/javaparser-cli && mvn -q -DskipTests package
#   산출물: target/astcli-1.0.0-shaded.jar
#   대안:   export REPO_AST_JAVAPARSER_JAR="/abs/path/astcli-1.0.0-shaded.jar"

# E7: JDT LS — jdtls 실행 파일 + Java 21+ 런타임 필요
#   (Eclipse JDT LS는 구동에 Java 21+ 요구, 컴파일 대상은 1.8–25 지원)

# E10: 테스트 실행 JDK
#   JDK 17/21 LTS = inline mock-maker 완전 지원(권장)
#   JDK 24/25 = Mockito 5.16+(ByteBuddy 1.17+) 또는 -Dnet.bytebuddy.experimental=true 필요
```

근거: `mcp/requirements.txt`·`mcp/javaparser-cli/README.md`·`.lsp.json`(저장소), Eclipse JDT LS Java 21 런타임 요구(2025-03 SDK 4.35), Mockito/ByteBuddy Java 25 class-file 69 미지원(Mockito ≤5.13).

---

## 비대화형/CI 자동 세팅 흐름

```
for item in [E2, ...결정적]:                     # 런타임 필수(MCP SDK 등)
    if not detect(item):
        run(auto_fix_command)        # pip install
        if not detect(item):         # 재검증
            return failed(item, remediation)   # 자동 세팅 실패 → 중단
run_best_effort(E6)                  # JavaParser jar: mvn package 시도, 실패해도 degrade(중단 아님)
for item in [E1, E8, E9, E10]:                 # 비결정적/시스템 필수
    if not detect(item):
        return failed(item, remediation)        # 질문 불가 → 중단(HarnessRequest 사전지정 요청)
# E4·E5·E6(JavaParser jar용 JDK/Maven/빌드)·E7(JDT LS)은 선택: 미가용이면 중단하지 않고
# 각각 정규식·AST-only로 degrade(경고)로 진행한다.
```

대화형은 위 `run(auto_fix_command)`를 **AskUserQuestion 확인 후** 실행하고, 비결정적 항목은 **질문**으로 채운다.

---

## 통과 기준

- E1·E2·E3(런타임 필수) **통과** + E8·E9(빌드도구·프로파일) **확정** + E10(실행 JDK 호환) **확인** → 0단계(configure-harness 인터뷰)로 진행. **E4·E5·E6(JavaParser jar용 JDK/Maven/빌드)와 E7(JDT LS)은 선택** — 미가용이면 각각 정규식·AST-only로 degrade(차단하지 않음).
- **E11(빌드 능력)·E12(캐시 프라이밍)**는 0.5단계 직후 **0.6단계**에서 처리한다(6단계 run-tests 이전 필수). 대화형=승인 후 주입/프라이밍, CI=미비 시 remediation 중단.
- 하나라도 미충족(대화형에서 사용자가 중단 선택 / CI에서 자동 세팅 실패·비결정적) → `status:"failed"`, `errors`에 항목과 remediation 명시, 파이프라인 **미시작**.
