# test-autoevermation-harness

Claude Code용 **Spring 테스트코드 자동 생성 하네스**를 배포하는 플러그인 마켓플레이스 저장소.

이 저장소는 Claude Code 마켓플레이스 카탈로그(`.claude-plugin/marketplace.json`)와
배포 대상 플러그인(`spring-test-harness-plugin/`), 그리고 설계·검증 산출물(`result_report/`)을 포함한다.

---

## 설치 (Claude Code)

```text
# 1) 마켓플레이스 등록
/plugin marketplace add 1223v/test-autoevermation-harness

# 2) 플러그인 설치
/plugin install spring-test-harness@test-autoevermation-harness
```

설치 후 `/spring-test-harness:full-pipeline` 명령이 인식되면 정상이다.

업데이트는 저장소에 변경을 push 하면 되고, 사용자는 `/plugin marketplace update`로 갱신한다.
플러그인 버전은 `spring-test-harness-plugin/.claude-plugin/plugin.json`의 `version`(현재 `0.2.2`)에 고정되어,
이 값이 바뀔 때만 사용자에게 업데이트가 전달된다.

### MCP 서버 런타임 (선택, 권장)

플러그인의 공유 MCP 3종은 Python(`mcp[cli]`)으로 동작한다.

```bash
pip install -r spring-test-harness-plugin/mcp/requirements.txt   # Python 3.10+
# (선택) 정확한 Java AST 백엔드 — 없으면 정규식 fallback
cd spring-test-harness-plugin/mcp/javaparser-cli && mvn -q -DskipTests package
```

---

## 저장소 구성

```
test-autoevermation-harness/
├── .claude-plugin/
│   └── marketplace.json        ← 마켓플레이스 카탈로그 (이 저장소를 마켓플레이스로 만든다)
├── spring-test-harness-plugin/ ← 배포 대상 플러그인 (자체 .claude-plugin/plugin.json 포함)
└── result_report/              ← 설계 보고서·원칙 감사·검증 기록·드라이런 샘플 (런타임 불필요)
```

플러그인 자체 문서는 [`spring-test-harness-plugin/README.md`](spring-test-harness-plugin/README.md),
설계·검증 근거는 [`result_report/`](result_report/)를 참조한다.

---

## 라이선스

Apache-2.0
