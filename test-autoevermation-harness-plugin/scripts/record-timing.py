#!/usr/bin/env python3
"""Record only observed stage telemetry; unknown usage is absent, never zero.

SubagentStart/SubagentStop provide wall-clock observations. Token counts are optional
host-supplied observations, not guaranteed by the Claude hook contract.
https://code.claude.com/docs/en/hooks
"""
from __future__ import annotations
import argparse
import json
import os
import runpy
import tempfile


def load(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            value = json.load(fh)
        if isinstance(value, dict) and isinstance(value.get('stages'), list):
            return value
    except (OSError, ValueError):
        pass
    return {'stages': []}


def recompute(doc: dict) -> dict:
    stages = doc.get('stages', [])
    totals = {}
    for key in ('total_tokens', 'duration_ms'):
        observed = [s[key] for s in stages if isinstance(s.get(key), int) and s[key] >= 0]
        if observed:
            totals[key] = sum(observed)
            totals[key + '_observed_stages'] = len(observed)
    if 'duration_ms' in totals:
        totals['total_duration_seconds'] = round(totals['duration_ms'] / 1000, 1)
    doc['totals'] = totals
    for label, key in (('slowest', 'duration_ms'), ('most_expensive', 'total_tokens')):
        observed = [s for s in stages if key in s]
        doc[label] = max(observed, key=lambda s: s[key])['stage'] if observed else None
    return doc


def record(workspace, stage, agent='', model='', tokens=None, duration_ms=None):
    os.makedirs(workspace, exist_ok=True)
    bootstrap = os.path.join(os.path.dirname(__file__), '..', 'mcp', 'bootstrap.py')
    lock_type = runpy.run_path(bootstrap)['InstallLock']
    with lock_type(os.path.join(workspace, '.timing.lock')):
        path = os.path.join(workspace, 'timing.json')
        doc = load(path)
        entry = {'stage': stage, 'agent': agent, 'model': model}
        for key, value in (('total_tokens', tokens), ('duration_ms', duration_ms)):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                entry[key] = value
        doc['stages'] = [s for s in doc['stages'] if s.get('stage') != stage] + [entry]
        recompute(doc)
        fd, temp = tempfile.mkstemp(prefix='.timing-', dir=workspace)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', default='_workspace')
    ap.add_argument('--stage', required=True)
    ap.add_argument('--agent', default='')
    ap.add_argument('--model', default='')
    ap.add_argument('--tokens', type=int)
    ap.add_argument('--duration-ms', type=int)
    args = ap.parse_args()
    record(args.workspace, args.stage, args.agent, args.model, args.tokens, args.duration_ms)
    print('recorded observed telemetry for ' + args.stage)
    return 0

if __name__ == '__main__': raise SystemExit(main())
