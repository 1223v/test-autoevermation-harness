#!/usr/bin/env python3
"""Append a stage's token/time telemetry to _workspace/timing.json.

서브에이전트 완료 알림의 total_tokens/duration_ms는 그 시점에만 접근 가능하다.
오케스트레이터(full-pipeline)가 각 단계 완료 직후 이 스크립트를 호출해 누적한다.

Usage:
  record-timing.py --workspace _workspace --stage 02_ast \
      --agent ast-structure-analyzer --model inherit \
      --tokens 63505 --duration-ms 444344

근거: revfactory/harness references/skill-testing-guide.md §3-3, skill-writing-guide.md §7.
표준 라이브러리만 사용한다(추가 의존성 없음).
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def load(path: str) -> dict:
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {"stages": [], "totals": {}, "slowest": None, "most_expensive": None}


def recompute(doc: dict) -> dict:
    stages = doc.get("stages", [])
    tok = sum(int(s.get("total_tokens") or 0) for s in stages)
    dur = sum(int(s.get("duration_ms") or 0) for s in stages)
    doc["totals"] = {
        "total_tokens": tok,
        "duration_ms": dur,
        "total_duration_seconds": round(dur / 1000.0, 1),
    }
    if stages:
        doc["slowest"] = max(stages, key=lambda s: int(s.get("duration_ms") or 0)).get("stage")
        doc["most_expensive"] = max(
            stages, key=lambda s: int(s.get("total_tokens") or 0)
        ).get("stage")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="Append stage telemetry to timing.json")
    ap.add_argument("--workspace", default="_workspace")
    ap.add_argument("--stage", required=True)
    ap.add_argument("--agent", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokens", type=int, default=0)
    ap.add_argument("--duration-ms", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    path = os.path.join(args.workspace, "timing.json")
    doc = load(path)

    # Idempotent on stage name: replace an existing entry for the same stage.
    doc["stages"] = [s for s in doc.get("stages", []) if s.get("stage") != args.stage]
    doc["stages"].append(
        {
            "stage": args.stage,
            "agent": args.agent,
            "model": args.model,
            "total_tokens": args.tokens,
            "duration_ms": args.duration_ms,
        }
    )
    doc = recompute(doc)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)

    print(
        f"recorded {args.stage}: {args.tokens} tok / {args.duration_ms} ms "
        f"| totals: {doc['totals']['total_tokens']} tok, "
        f"{doc['totals']['total_duration_seconds']}s | slowest={doc['slowest']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
