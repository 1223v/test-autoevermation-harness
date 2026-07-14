---
name: setup-harness
description: Spring 테스트 하네스를 돌리기 위한 환경 세팅(Phase E — Python·MCP 런타임, MCP 라이브 연결, JDK 21+, JavaParser jar, JDT LS)과 상태줄 설치를 수행한다. "환경 세팅", "하네스 설치", "환경 설정", "초기 설치", "MCP 설치", "setup", "세팅해줘", "환경 점검/복구"처럼 실행 환경 준비가 필요한 상황에서 자동 호출된다. 플러그인 설치 후 최초 1회 실행하며, 환경이 깨졌을 때 재실행하면 빠진 항목만 멱등하게 복구한다. CI(claude -p)에서는 질문 없이 결정적 항목을 자동 세팅하고, 미충족 시 하드 중단한다.
---

## 목적

하네스 **실행 전에 환경을 전부 갖춰 놓는 전용 명령**이다. `full-pipeline`/`configure-harness`는 이제 **환경 세팅을 수행하지 않는다** — 시작 시 검증 프로브(E-verify)만 돌리고 미충족이면 이 스킬을 실행하라고 안내하며 중단한다. 즉 **세팅과 파이프라인 실행이 분리**되어 있고, 세팅의 수행 주체는 이 스킬 하나다.

담당 범위:

- **E1~E10 환경 세팅** — Python 3.10+ · MCP SDK · MCP 서버 3종 등록 · **E3b MCP 라이브 연결 검증** · JDK 21+ · mvnw · JavaParser CLI jar · JDT LS(+Java 21) · 테스트 실행 JDK ↔ Mockito 호환.
- **S1 상태줄 설치** — TAM 진행률 상태줄(consent 기반, 선택).

담당하지 **않는** 범위(경계):

- **E8·E9**(빌드도구·Spring 프로파일 감지) → `configure-harness` **0.5단계**. 대상 프로젝트의 데이터 감지라 세팅이 아니다.
- **E11·E12**(대상 프로젝트의 JaCoCo 능력 프로비저닝·의존성 캐시 프라이밍) → `configure-harness` **0.6단계**. 대상 빌드도구·프로파일·사용자 승인에 의존하므로 플러그인 환경 세팅 시점으로 앞당길 수 없다.

정본(SSOT): 항목 정의·감지 명령·세팅 명령·통과 기준은 [references/environment-setup.md](../../references/environment-setup.md). 이 스킬은 그 체크리스트의 **실행 절차**를 정의한다. 정책: [fallback-policy.md](../../references/fallback-policy.md) #2·#3·#20 — **degrade 금지**(정규식·AST-only 대체 없음).

---

## 자동 호출 조건

- 사용자가 "환경 세팅", "하네스 설치", "환경 설정", "초기 설치", "MCP 설치", "세팅해줘", "환경 점검", "환경 복구"와 같은 키워드를 사용할 때
- 플러그인 설치 직후 최초 1회
- `full-pipeline`/`configure-harness`가 E-verify 실패로 중단하며 이 스킬을 안내했을 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:setup-harness
```

> **위임 금지 — 메인 루프 전용.** 이 스킬은 MCP `health` 도구 호출과 `AskUserQuestion`을 사용하는데, 둘 다 **서브에이전트에서 사용할 수 없다**. `Task(subagent_type=...)`로 위임하지 말고 메인 루프에서 직접 수행한다.

---

## 인터랙티브 모드 감지

다음 중 하나라도 해당하면 **CI 모드**(질문 없이 자동 세팅)로 동작한다:

- 환경 변수 `CI=true` 또는 `CLAUDE_NO_PROMPT=true`
- `claude -p` 플래그로 호출된 비대화형 세션

---

## 단계별 절차

### TODO 리스트로 진행한다

시작 시 `TodoWrite`로 아래 항목을 만들고 `pending → in_progress → completed`로 하나씩 체크한다(진척 가시화).

```
E1 Python 3.10+ · E2 MCP SDK · E3 MCP 서버 3종 등록 · E3b MCP 라이브 연결 검증 ·
E4 JDK 21+ · E5 mvnw · E6 JavaParser jar · E7 JDT LS(+Java 21) · E10 실행 JDK↔Mockito ·
S1 상태줄 설치(선택)
```

각 항목의 **감지 명령 · 세팅 명령 · 대화형/CI 분기 · 연계 정책**은 [environment-setup.md](../../references/environment-setup.md)의 체크리스트 표와 「세팅 명령 레퍼런스」가 정본이다 — 여기서 표를 재복제하지 않는다. 그 문서를 Read해 항목별 명령을 그대로 사용한다.

**각 항목 공통 절차: 감지(detect) → (미충족 시) 세팅 → 재감지(verify) → `completed`.** 재감지로 통과를 확인하기 전에는 절대 `completed`로 표시하지 않는다.

---

### 세팅 방식 (정책: environment-setup.md 핵심 원칙 2·3)

- **대화형 — 항목별로 함께 세팅**: 자동으로 고칠 수 있는 항목(E1·E2·E6·E7)은 항목마다
  `AskUserQuestion("〈항목〉이 없습니다. 지금 함께 세팅할까요?")` → "예"면 그 자리에서 설치/빌드 실행
  (E1+E2=`node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs --ensure-only`, E6=`cd mcp/javaparser-cli && ./mvnw -q -DskipTests package`,
  E7=`node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs script ${CLAUDE_PLUGIN_ROOT}/scripts/setup_jdtls.py`)
  → **재감지 검증** → `completed`. "아니오"면 `status:"failed"` 중단.
  assist 항목(E4 JDK 21+, E10 실행 JDK, 그리고 자동 설치 실패·`HARNESS_AUTO_PYTHON=0`인 E1)은 설치/경로 안내 질문 —
  사용자가 못 갖추면 중단.
- **비대화형/CI — 항상 자동 세팅**: 결정적 항목(E1·E2·E6·E7)은 질문 없이 위 명령을 **자동 실행** 후 재검증.
  자동 세팅이 실패하거나 시스템 항목(E4 JDK 21+)이 없으면, 그리고 E3b MCP 연결 검증이 실패하면
  `status:"failed"` + remediation으로 하드 중단한다.
- **E3b·E4·E5·E6·E7은 모두 필수** — 미가용이면 자동 세팅을 시도하고, 실패하면 **하드 중단**한다.
  **정규식·AST-only degrade로 진행하지 않는다.**

---

### E3b 실행 블록 — MCP 라이브 연결 검증 (E3 직후, 필수)

E3의 모듈 로드 검사만으로는 플러그인 MCP 등록 실패(세션에 도구 미노출)를 못 잡는다. 따라서 3개 서버의 무부작용 `health` 도구를 **실제로 호출**해 연결을 검증한다.

```
repo-ast-mcp.health()   → { server, pluginVersion, javaparser:{jarFound, jarPath, javaOk, requireJavaparser}, allowRoot }
spec-doc-mcp.health()   → { server, pluginVersion, ... }
build-test-mcp.health() → { server, pluginVersion, networkAllowed, ... }
```

- **3종 모두 성공**: 응답의 `pluginVersion`과 repo-ast의 `javaparser` 상태를 요약에 기록하고 E3b를 `completed`로 표시한다.
- **도구 미존재 또는 호출 실패**(어느 서버든): 침묵 fallback·Grep/Read 대체 없이 **하드 중단**한다 — `status:"failed"` + remediation:
  1. 플러그인이 활성화되어 있는지 확인(`/plugin` 목록에 `test-autoevermation-harness-plugin`).
  2. `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs --ensure-only`로 런타임을 재프로비저닝.
  3. `/reload-plugins` 또는 Claude Code 재시작으로 MCP 서버를 재등록.
  4. SessionStart 훅 stderr 확인.
- **repo-ast health의 `javaparser.jarFound:false`**: jar 미빌드 상태다 — E6 세팅(자동 빌드)으로 연결한다. `.mcp.json`이 `REPO_AST_REQUIRE_JAVAPARSER=1`이므로 jar 없이는 이후 파싱이 `JAVAPARSER_REQUIRED`로 실패한다.

> **`lspAvailable`은 E7 통과 시 항상 `true`다** — E7(JDT LS)은 필수 항목이므로 `jdtls`(PATH/프로비저닝) + `.lsp.json`(plugin.json `lspServers`로 등록) + Java 21+ 런타임이 모두 통과해야 세팅이 완료된다. E7이 미가용이면 이 스킬이 하드 중단하므로, **`lspAvailable:false` 상태로 파이프라인에 진입하는 경로는 없다.** `configure-harness`가 산출하는 `HarnessConfig.lspAvailable`이 항상 `true`인 근거이며, `analyze-source`/`full-pipeline`의 LSP 보강(정의이동·참조탐색)은 이 전제 위에서 항상 활성화된다.

---

### S1 단계: 상태줄 설치 (선택 — 실패해도 게이트가 아니다)

TAM 상태줄(플러그인 버전·full-pipeline 진행률·현재 단계)을 설치한다. 모든 설치/제거/원복 로직의 SSOT는 `hooks/statusline-autosetup.py`이며 이 스킬은 그 스크립트를 **호출만** 한다(수작업 `settings.json` 편집 금지). 정본 진입점(크로스플랫폼):

```bash
# <AUTOSETUP> 로 줄여 표기
node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" script "${CLAUDE_PLUGIN_ROOT}/hooks/statusline-autosetup.py"
```

절차:

1. `<AUTOSETUP> --status`로 현재 상태를 확인한다.
2. **이미 설치됨(`consent=granted`)** → 아무것도 하지 않고 `completed`(멱등).
3. **`consent=declined`** → **그대로 존중하고 건너뛴다.** 사용자가 이전에 거절한 결정을 임의로 뒤집지 않는다(사용자가 이번에 명시적으로 상태줄 설치를 요청한 경우에만 재설치).
4. **미결정 + 대화형** → `AskUserQuestion("full-pipeline 진행률을 보여주는 TAM 상태줄을 설치할까요?", options=["예 — 설치", "아니오 — 설치 안 함"])`
   → 예: `<AUTOSETUP> --install --consent granted` / 아니오: `<AUTOSETUP> --install --consent declined`
5. **미결정 + CI/비대화형** → **건너뛴다**(질문 불가). SessionStart 훅이 이후 대화형 세션에서 처리한다.

**S1 실패는 `errors`가 아니라 `warnings`다** — 상태줄은 선택 기능이므로 설치 실패가 `status:"failed"`를 유발하지 않는다. 제거·재설치·디버그는 [`setup-statusline`](../setup-statusline/SKILL.md) 스킬을 쓴다.

---

## 통과 기준 (정본: [environment-setup.md](../../references/environment-setup.md) 「통과 기준」)

필수 항목 **E1·E2·E3·E3b(런타임·MCP 라이브 연결) + E4(JDK 21+)·E5(mvnw)·E6(JavaParser jar)·E7(JDT LS) + E10(실행 JDK 호환)**이 전부 `completed`여야 세팅 완료(`status:"ok"`)다. 하나라도 미충족이면 `status:"failed"` + `errors`에 항목·remediation을 담아 중단한다. **S1(상태줄)은 선택** — 미설치·실패는 `warnings`에만 기록한다.

## 멱등 재실행

이 스킬은 몇 번을 다시 실행해도 안전하다. 재실행 시 모든 항목을 **다시 감지**해 **빠진 항목만** 세팅한다 — 이미 통과한 항목은 건드리지 않는다(재빌드·재다운로드 없음). 환경이 깨졌을 때(플러그인 업데이트로 venv 경로 변경, `mvn clean`으로 jar 소실, JDK 교체 등) 그대로 다시 부르면 된다.

---

## 출력

```json
{
  "status": "ok",
  "summary": {
    "E1": "ok (python 3.12.4)",
    "E2": "ok (mcp[cli] 1.4.1 @ plugin venv)",
    "E3": "ok (repo-ast, spec-doc, build-test)",
    "E3b": "ok (health x3, pluginVersion 0.25.0)",
    "E4": "ok (java 21.0.3)",
    "E5": "ok (bundled mvnw)",
    "E6": "ok (target/astcli-1.0.0-shaded.jar — built)",
    "E7": "ok (jdtls provisioned)",
    "E10": "ok (JDK 21 LTS — inline mock-maker 지원)",
    "S1": "installed (consent granted)"
  },
  "warnings": [],
  "errors": [],
  "nextActions": [
    "/test-autoevermation-harness-plugin:full-pipeline 로 테스트 파이프라인을 실행하세요"
  ]
}
```

실패 예시:

```json
{
  "status": "failed",
  "summary": { "E4": "failed (java 17 — 21+ 필요)" },
  "warnings": [],
  "errors": [
    "E4: JDK 21+ 미충족. JavaParser jar 빌드와 JDT LS 구동에 Java 21+가 필요합니다. sdkman/brew로 설치 후 JAVA_HOME을 지정하고 다시 실행하세요"
  ],
  "nextActions": ["JDK 21+ 설치 후 /test-autoevermation-harness-plugin:setup-harness 재실행"]
}
```

---

## 실패 처리

| 상황 | 처리 방식 |
|---|---|
| **E3b MCP 라이브 연결 실패 (#20)** | 대화형·CI 모두 `status:"failed"` + 4단계 remediation(위 E3b 블록). Grep/Read 대체 금지 |
| **E6 JavaParser jar 빌드 실패 (#2)** | `JAVAPARSER_REQUIRED` 하드 중단. 정규식 degrade 없음. 오프라인이면 사전 빌드 jar를 `REPO_AST_JAVAPARSER_JAR`로 지정 안내 |
| **E7 JDT LS 프로비저닝 실패 (#3)** | 하드 중단. AST-only degrade 없음. 오프라인이면 jdtls 사전 설치 안내 |
| **E4 JDK 21+ 미충족** | assist 항목 — 자동 설치 불가. 대화형=설치 안내 질문 / CI=하드 중단 |
| **E10 실행 JDK ↔ Mockito 비호환** | 대화형=`AskUserQuestion`(17/21 LTS 전환 / Mockito 5.16+ / `-Dnet.bytebuddy.experimental=true`) / CI=중단 |
| **S1 상태줄 설치 실패** | **중단하지 않는다** — `warnings`에 기록하고 `status:"ok"` 유지(선택 기능) |
| 대화형에서 사용자가 세팅을 거부 | `status:"failed"` + 해당 항목 remediation. 임의 degrade 진행 금지 |

보안: 세팅 명령은 플러그인 루트(`${CLAUDE_PLUGIN_ROOT}`) 내부 스크립트만 실행한다. 첫 세팅 1회는 네트워크가 필요하다(uv Python 설치, Maven 의존성 해석, JDT LS tarball) — 완전 오프라인 환경의 대안은 environment-setup.md 「세팅 명령 레퍼런스」의 오프라인 대안을 따른다.
