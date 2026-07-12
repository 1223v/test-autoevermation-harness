---
name: setup-statusline
description: TAM 상태줄(플러그인 버전·full-pipeline 진행률·현재 단계)을 Claude Code statusLine에 설치하거나 제거한다. "상태줄 설치", "statusline 설정", "TAM 상태줄", "진행률 표시", "상태줄 제거/원복"처럼 상태줄 구성이 필요한 상황에서 자동 호출된다.
---

## 목적

Claude Code 상태줄에 아래 형식의 줄을 한 줄 추가한다(공식 문서상 statusLine stdout의 각 줄은 별도 행으로 렌더링됨):

```
[Test-AutoEverMation#0.20.1]                                   ← 파이프라인 없음(버전만)
[Test-AutoEverMation#0.20.1] 43% | stage 4: generate-scenarios ← full-pipeline 진행 중
[Test-AutoEverMation#0.20.1] 79% | ↩ resumed @ stage 8: measure-coverage ← 상태 복원 재개(durable resume)
[Test-AutoEverMation#0.20.1] 100% | done (ok)                  ← 완료(pipeline_result.json 존재)
```

**대부분 이 스킬을 수동으로 부를 필요가 없다.** 설치 후 첫 세션에서 `SessionStart` 훅
(`hooks/statusline-autosetup.py`)이 "상태줄을 설치할까요?"를 **한 번** 묻고, 승인하면 이후 자동으로
유지된다(§자동화). 이 스킬은 그 확인에 응답하거나(설치/거절), 나중에 수동으로 제거·재설치할 때 쓴다.

동작 원리: 플러그인은 main `statusLine`을 자체 settings로 설정할 수 없으므로(공식: `agent`/
`subagentStatusLine`만 적용) 전역 `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`을 직접 편집한다.
TAM이 top-level `statusLine`을 **소유**하고 기존 커맨드(예: OMC HUD)는 `test-autoevermation-statusline.json`의
`delegate`로 보존해 전역 런처가 계속 실행한다. 모든 설치/제거/원복 로직의 SSOT는
`hooks/statusline-autosetup.py`이며, 이 스킬은 그 스크립트를 호출만 한다(수작업 JSON 편집 금지).

---

## 플러그인 루트 확인 (모든 절차 공통)

- `~/.claude/plugins/installed_plugins.json`에서 `test-autoevermation-harness-plugin@`으로 시작하는 키의
  `installPath`를 `${CLAUDE_PLUGIN_ROOT}`로 취한다. 미등록(로컬 dev)이면 이 SKILL.md가 로드된 경로의 2단계 상위.
- **주의**: Bash에서 `${CLAUDE_PLUGIN_ROOT}`에 의존하지 않는다 — 훅/MCP 프로세스에만 주입되는 변수다.
- 아래 명령의 정본 진입점은 `node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" script "${CLAUDE_PLUGIN_ROOT}/hooks/statusline-autosetup.py"`
  이다(크로스플랫폼 — launch.cjs가 파이썬을 해석). 이를 `<AUTOSETUP>`으로 줄여 표기한다.

---

## 설치 / 재설치 ("설치", "상태줄 켜줘", 최초 확인에 "설치" 응답 시)

```bash
<AUTOSETUP> --install --consent granted
```

- 전역 wrapper·런처를 `${CLAUDE_CONFIG_DIR:-~/.claude}/`에 복사하고, `settings.json`의 `statusLine`을
  런처로 점유하며, 기존 커맨드를 `delegate`로 포획한다(이미 TAM 소유면 기존 delegate 유지 — 이중 래핑 금지).
  `consent=granted`가 기록되어 **이후 세션부터 자동 유지·재점유**된다.
- 멱등하다. 이미 설치돼 있으면 `settings.json`을 바꾸지 않는다(`changed:false` 반환). 다른 도구가
  상태줄을 되가져간 경우 이 명령(또는 다음 세션 시작)이 자동으로 재점유한다.

**스모크 테스트**(선택):

```bash
echo '{"workspace":{"current_dir":"'$PWD'"}}' | node "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/test-autoevermation-statusline-launch.cjs"
```

기대: 기존 상태줄 출력(있다면) + `[Test-AutoEverMation#<version>]`으로 시작하는 마지막 줄, exit 0.

---

## 자동 설치 거절 (최초 확인에 "설치 안 함" 응답 시)

```bash
<AUTOSETUP> --install --consent declined
```

`settings.json`은 건드리지 않고 `consent=declined`만 기록한다 → SessionStart 훅이 다시 묻거나 설치하지
않는다. 나중에 마음이 바뀌면 위 "설치" 명령을 실행하면 된다. (전역 kill switch는 환경변수
`TAM_STATUSLINE_AUTO=0`.)

---

## 제거 / 원복 ("제거", "원복", "uninstall" 요청 시)

```bash
<AUTOSETUP> --uninstall
```

- `settings.json`의 `statusLine`을 `delegate`(원래 상태줄)로 원복한다. delegate가 없었으면 `statusLine`
  키 자체를 제거한다(JSON 라운드트립).
- 전역 wrapper·런처 사본을 삭제하고 `consent=declined`로 남겨 재설치를 막는다.
- 백업 파일(`settings.json.test-autoevermation-backup-*`)은 보존한다(사용자가 직접 정리).

> **참고 — 플러그인 uninstall 시 자동 원복.** Claude Code에는 uninstall 훅이 없어 `/plugin uninstall`이
> 전역 `settings.json` 수정을 되돌리지 못한다. 이를 위해 전역 wrapper 사본이 렌더마다 플러그인 설치
> 여부를 확인해, 사라졌으면 스스로 위와 동일한 원복(self-heal)을 1회 수행한다 → uninstall 후 재시작 시
> 첫 상태줄 렌더에서 자동 복구된다. 위 `--uninstall`은 플러그인을 지우기 전에 **즉시** 원복하고 싶을 때 쓴다.

---

## 상태 확인 / 디버그

```bash
<AUTOSETUP> --status
```

현재 config·statusLine 커맨드·전역 사본 존재 여부를 JSON으로 출력한다.

---

## 알려진 제약 (사용자 안내용)

- **플러그인 업데이트 후**: 전역 사본은 SessionStart 훅이 매 시작마다 최신본으로 갱신하므로 보통 손댈 필요
  없다. 훅이 꺼진 환경이면 위 "설치" 명령을 재실행한다.
- **OMC `/statusline`·`omc-setup`·`/hud` 재실행**: 이들이 상태줄을 OMC HUD로 되돌려도, 다음 세션 시작에
  TAM이 자동 재점유하고 OMC HUD를 delegate로 다시 포획한다(수동 개입 불필요).
- **하위 디렉터리에서 세션 시작**: `_workspace/`는 프로젝트 루트(`workspace.current_dir`) 직하만 확인하므로,
  루트 밖에서는 유휴 표시(`[Test-AutoEverMation#x.y.z]`)만 나온다.
- 표시 단계 라벨↔산출물 매핑의 SSOT는 `skills/full-pipeline/references/orchestration-detail.md` §2이며, 래퍼
  스크립트 상단 `ORDER` 리스트가 이를 미러링한다. 파이프라인 산출물 규약 변경 시 `ORDER`도 함께 갱신한다.
- **상태 복원(durable resume) 표시**: `_workspace/`가 휘발한 뒤 full-pipeline Phase 0가 영속 증거로 재개하면
  `_workspace/_resume.json`(`{entryStage, entryLabel, ts}`, 규약 SSOT: orchestration-detail.md §2-1)을 남긴다.
  상태줄은 이를 읽어 표시 단계를 재진입 지점으로 clamp하고 `↩ resumed @ <단계>`로 표기한다 — 재개 지점보다
  뒤의 stale 산출물이 있어도 과대표시하지 않는다. `pipeline_result.json`이 생기면 `100% | done`이 우선한다.
