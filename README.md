# test-autoevermation-harness

Claude Code용 **Spring 테스트코드 자동 생성 하네스**를 배포하는 플러그인 마켓플레이스 저장소.

이 저장소는 Claude Code 마켓플레이스 카탈로그(`.claude-plugin/marketplace.json`)와
배포 대상 플러그인(`test-autoevermation-harness-plugin/`)을 포함한다.

---

## 설치 (Claude Code)

```text
# 1) 마켓플레이스 등록
/plugin marketplace add 1223v/test-autoevermation-harness

# 2) 플러그인 설치
/plugin install test-autoevermation-harness-plugin@test-autoevermation-harness
```

설치 후 `/test-autoevermation-harness-plugin:full-pipeline` 명령이 인식되면 정상이다.

업데이트는 저장소에 변경을 push 하면 되고, 사용자는 `/plugin marketplace update`로 갱신한다.
플러그인 버전은 `test-autoevermation-harness-plugin/.claude-plugin/plugin.json`의 `version`에 고정되어,
이 값이 바뀔 때만 사용자에게 업데이트가 전달된다.

### MCP 서버 런타임 (v0.16.0부터 필수)

플러그인의 공유 MCP 3종은 Python(`mcp[cli]`)으로 동작하며, 파이프라인 시작 전 Phase E `E3b`가
`health` 도구 3종을 실호출해 연결을 검증한다(실패 시 하드 중단). JavaParser AST 백엔드와 JDT LS도
필수다 — **JDK 21+**가 있어야 하고, 시스템 Maven은 불필요(`mcp/javaparser-cli`에 `mvnw` 동봉)하다.
최초 1회는 Maven 의존성·`mvnw` 배포판·JDT LS tarball 다운로드를 위한 네트워크가 필요하다.

```bash
pip install -r test-autoevermation-harness-plugin/mcp/requirements.txt   # Python 3.10+
# JavaParser AST 백엔드 빌드 (필수) — 시스템 Maven 불요, mvnw 동봉
cd test-autoevermation-harness-plugin/mcp/javaparser-cli && ./mvnw -q -DskipTests package
```

---

## 제거

```text
# 플러그인만 제거
/plugin uninstall test-autoevermation-harness-plugin@test-autoevermation-harness

# 마켓플레이스 등록까지 해제 — 이 마켓플레이스에서 설치한 플러그인도 함께 제거된다(공식 동작)
/plugin marketplace remove test-autoevermation-harness
```

- 제거하지 않고 잠시 끄려면 `/plugin disable test-autoevermation-harness-plugin@test-autoevermation-harness`,
  다시 켜려면 같은 인자로 `/plugin enable`.
- 로컬 설치(복사/심볼릭 링크)를 사용한 경우에는 `~/.claude/plugins/test-autoevermation-harness-plugin`을
  삭제한 뒤 Claude Code를 재시작한다.
- 변경 사항은 `/reload-plugins` 또는 세션 재시작으로 반영된다.

---

## 재설정

**최신 버전 반영(일반 재설정):**

```text
/plugin marketplace update test-autoevermation-harness
/reload-plugins
```

**설치 상태가 깨졌을 때(스킬 미노출·MCP 서버 에러 지속):** 공식 트러블슈팅 절차대로 플러그인 캐시를
비우고 재설치한다.

```bash
rm -rf ~/.claude/plugins/cache
```

이후 Claude Code를 재시작하고 위 [설치](#설치-claude-code) 절차를 다시 실행한다.

**하네스 실행 상태 재설정:** 파이프라인 중간 산출물은 대상 프로젝트 루트의 `_workspace/`에 저장된다
(부분 재실행용). 이 디렉터리를 삭제하면 다음 실행이 처음부터(0단계 `configure-harness` 인터뷰 포함)
시작된다 — 새 입력으로 다시 돌리면 기존 산출물은 자동으로 `_workspace_{timestamp}/`로 보존되므로
수동 삭제는 선택이다. `test_docs/`는 사람이 읽는 영속 산출물이므로 유지한다. 상태줄을 설치했다면
`/test-autoevermation-harness-plugin:setup-statusline`에 "제거"를 요청해 원복한다.
상세: [docs/GUIDE.md](test-autoevermation-harness-plugin/docs/GUIDE.md).

---

## 저장소 구성

```
test-autoevermation-harness/
├── .claude-plugin/
│   └── marketplace.json        ← 마켓플레이스 카탈로그 (이 저장소를 마켓플레이스로 만든다)
└── test-autoevermation-harness-plugin/ ← 배포 대상 플러그인 (자체 .claude-plugin/plugin.json 포함)
```

플러그인 자체 문서는 [`test-autoevermation-harness-plugin/README.md`](test-autoevermation-harness-plugin/README.md),
동작 원리·사용법 종합 가이드는 [`test-autoevermation-harness-plugin/docs/GUIDE.md`](test-autoevermation-harness-plugin/docs/GUIDE.md)를 참조한다.

---

## 라이선스

Apache-2.0
