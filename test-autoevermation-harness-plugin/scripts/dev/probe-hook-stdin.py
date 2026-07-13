#!/usr/bin/env python3
"""probe-hook-stdin.py — 개발용 훅 계약 프로브 (배선하지 않음; 계약 드리프트 재검용).

PreToolUse/PostToolUse 등 임의 훅에 임시 배선하면 stdin으로 들어오는 훅 페이로드
전체를 JSONL로 기록한다. 가드 스크립트가 의존하는 필드(agent_id/agent_type,
tool_name, session_id, cwd, tool_input 스키마)가 Claude Code 업그레이드 후에도
유지되는지 실증할 때 사용한다.

기록 위치: $PROBE_HOOK_LOG 가 있으면 그 파일, 없으면 <cwd>/_workspace/.markers/probe.jsonl
출력: 항상 {} (무의견 allow) — 세션 동작에 영향을 주지 않는다.

임시 배선 예 (프로젝트 .claude/settings.json):
  {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [
    {"type": "command", "command": "python3 /path/to/probe-hook-stdin.py"}]}]}}
"""

import json
import os
import sys
import time


def main() -> int:
    try:
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            payload = {"_unparsed": raw[:2000]}
        record = {"_probe_ts": time.time(), **(payload if isinstance(payload, dict) else {"_payload": payload})}

        log_path = os.environ.get("PROBE_HOOK_LOG")
        if not log_path:
            log_path = os.path.join(os.getcwd(), "_workspace", ".markers", "probe.jsonl")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 — 프로브는 어떤 경우에도 세션을 깨지 않는다
        pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
