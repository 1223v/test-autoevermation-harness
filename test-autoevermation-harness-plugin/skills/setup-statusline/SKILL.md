---
name: setup-statusline
description: TAM 상태줄(플러그인 버전·full-pipeline 진행률·현재 단계)을 Claude Code statusLine에 설치하거나 제거한다. "상태줄 설치", "statusline 설정", "TAM 상태줄", "진행률 표시", "상태줄 제거/원복"처럼 상태줄 구성이 필요한 상황에서 자동 호출된다.
---

## 목적

`~/.claude/settings.json`의 `statusLine` 커맨드를 이 플러그인의 래퍼 스크립트(`scripts/test-autoevermation-statusline.py`)로 교체한다. 래퍼는 기존 statusLine 커맨드(예: OMC HUD)를 그대로 실행해 출력한 뒤, 아래 형식의 줄을 한 줄 추가한다(공식 문서상 statusLine stdout의 각 줄은 별도 행으로 렌더링됨):

```
[Test-AutoEverMation#0.11.0]                                   ← 파이프라인 없음(버전만)
[Test-AutoEverMation#0.11.0] 43% | stage 4: generate-scenarios ← full-pipeline 진행 중
[Test-AutoEverMation#0.11.0] 100% | done (ok)                  ← 완료(pipeline_result.json 존재)
```

진행률은 현재 프로젝트 루트의 `_workspace/` 단계 산출물 존재 여부로 계산한다(파이프라인 수정 없음, 읽기 전용). 플러그인은 메인 statusLine을 스스로 설정할 수 없으므로(플러그인 settings.json은 `agent`/`subagentStatusLine` 키만 적용됨) 이 스킬이 사용자 승인 하에 설정을 대신한다.

---

## 설치 절차

TODO 리스트로 아래를 순서대로 수행한다.

### 1. 플러그인 루트 확인

- `~/.claude/plugins/installed_plugins.json`을 읽어 `test-autoevermation-harness-plugin@`으로 시작하는 키의 `installPath`를 취한다.
- 미등록(로컬 dev 설치)이면 이 SKILL.md가 로드된 경로의 2단계 상위 디렉터리(플러그인 루트)를 사용한다.
- **주의**: Bash에서 `${CLAUDE_PLUGIN_ROOT}`에 의존하지 않는다 — 훅/MCP 프로세스에만 주입되는 변수다.
- `<pluginRoot>/scripts/test-autoevermation-statusline.py`가 실제 존재하는지 확인한다. 없으면 중단하고 보고한다.

### 2. 멱등성 검사

`~/.claude/settings.json`을 읽는다(없으면 빈 객체로 간주).

- `statusLine.command`에 이미 `test-autoevermation-statusline.py`가 포함되어 있으면:
  - 경로가 1번에서 확인한 pluginRoot와 일치 → **"이미 설치됨"** 보고 후 종료.
  - 경로가 다르면(플러그인 업데이트로 캐시 경로 변경) → `command`만 새 경로로 갱신하고 종료. delegate 설정은 건드리지 않는다.
- 포함되어 있지 않으면 계속 진행.

### 3. 백업

`~/.claude/settings.json` → `~/.claude/settings.json.test-autoevermation-backup-<YYYYMMDD_HHMMSS>` 복사.

### 4. delegate 설정 기록

`~/.claude/test-autoevermation-statusline.json` 작성:

```json
{
  "delegate": "<현재 statusLine.command 문자열 그대로, 없으면 null>",
  "pluginRoot": "<1번의 pluginRoot>"
}
```

- **검증**: delegate 문자열에 `test-autoevermation-statusline.py`가 포함되면 안 된다(이중 래핑 금지). 포함되어 있다면 설정이 꼬인 상태이므로 기존 `test-autoevermation-statusline.json`의 delegate를 유지하고 사용자에게 보고한다.
- 기존 statusLine이 없었다면 `"delegate": null` — 래퍼는 TAM 줄만 출력한다.

### 5. statusLine 교체

`~/.claude/settings.json`을 JSON 라운드트립으로 편집(정규식/문자열 치환 금지, 다른 키 전부 보존):

```json
"statusLine": {
  "type": "command",
  "command": "python3 <pluginRoot>/scripts/test-autoevermation-statusline.py"
}
```

### 6. 스모크 테스트

```bash
echo '{"workspace":{"current_dir":"'$PWD'"}}' | python3 <pluginRoot>/scripts/test-autoevermation-statusline.py
```

기대: 기존 statusLine 출력(있다면) + `[Test-AutoEverMation#<version>]`으로 시작하는 마지막 줄, exit 0. 실패 시 3번 백업으로 원복하고 보고한다. 성공 시 "다음 상태줄 새로고침부터 반영"을 안내한다.

---

## 제거 절차 ("제거", "원복", "uninstall" 요청 시)

1. `~/.claude/test-autoevermation-statusline.json`의 `delegate`를 읽는다.
2. `~/.claude/settings.json`의 `statusLine.command`를 delegate 문자열로 복원한다. delegate가 `null`이었으면 `statusLine` 키 자체를 제거한다. (JSON 라운드트립 편집)
3. `~/.claude/test-autoevermation-statusline.json`을 삭제한다.
4. 백업 파일(`settings.json.test-autoevermation-backup-*`)은 보존한다(사용자가 직접 정리).

---

## 알려진 제약 (사용자 안내용)

- **플러그인 업데이트 후**: 마켓플레이스 설치에서는 캐시 경로가 버전별로 바뀔 수 있어 statusLine이 옛 경로를 가리키게 된다. 이 스킬을 재실행하면 2번 단계가 경로를 갱신한다.
- **OMC `/statusline`·`omc-setup` 재실행**: statusLine을 OMC HUD 커맨드로 되돌려 TAM 줄이 사라질 수 있다. 이 스킬을 재실행하면 복구된다.
- **하위 디렉터리에서 세션 시작**: `_workspace/`는 프로젝트 루트(`workspace.current_dir`) 직하만 확인하므로, 루트 밖에서는 유휴 표시(`[Test-AutoEverMation#x.y.z]`)만 나온다.
- 표시 단계 라벨↔산출물 매핑의 SSOT는 `skills/full-pipeline/references/orchestration-detail.md` §2이며, 래퍼 스크립트 상단 `ORDER` 리스트가 이를 미러링한다. 파이프라인 산출물 규약 변경 시 `ORDER`도 함께 갱신한다.
