#!/usr/bin/env python3
"""persist_astcli_jar.py — E6 산출물(astcli jar)을 업데이트 생존 위치로 영속화한다.

배경(공식문서): 플러그인 캐시 디렉토리(CLAUDE_PLUGIN_ROOT)는 버전 키 스냅샷이라
업데이트마다 경로가 바뀌고 구버전 디렉토리는 14일 후 삭제된다 — "treat it as
ephemeral and don't write state there". 반면 CLAUDE_PLUGIN_DATA는 업데이트에도
유지된다. astcli jar는 target/이 gitignore라 스냅샷에 절대 포함되지 않으므로,
빌드 직후 이 스크립트로 CLAUDE_PLUGIN_DATA/javaparser/에 복사해 두어야
업데이트 후에도 repo-ast가 하드실패하지 않는다(_locate_jar 3순위 후보).

사용 (launch.cjs script 모드 — stdlib 전용, venv 불필요):
  node "${CLAUDE_PLUGIN_ROOT}"/mcp/launch.cjs script \
       "${CLAUDE_PLUGIN_ROOT}"/scripts/persist_astcli_jar.py [--check]

  --check : 상태만 JSON으로 보고(빌드 스킵 판단용). persisted+fingerprint 일치면
            {"upToDate": true} — E6는 이 경우 Maven 빌드를 건너뛴다.
  (기본)  : target/의 shaded jar를 data로 복사하고 소스 지문 마커를 기록한다.

소스 지문은 pom.xml + src/**/*.java의 sha256 16-hex다. 정본 쌍둥이:
mcp/repo_ast_server.py _source_fingerprint() — tests/test_update_persistence.py가
두 구현의 동일성을 강제한다.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = PLUGIN_ROOT / "mcp" / "javaparser-cli"
DATA_JAR_SUBDIR = "javaparser"
FINGERPRINT_BASENAME = "astcli.fingerprint"


def data_dir() -> Path:
    """bootstrap.py data_dir()와 동일 해석: CLAUDE_PLUGIN_DATA → .plugin-data 폴백."""
    env = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if env:
        return Path(env)
    return PLUGIN_ROOT / "mcp" / ".plugin-data"


def source_fingerprint(cli_dir: Path = CLI_DIR) -> str | None:
    """pom.xml + src/**/*.java의 16-hex sha256. 실패 시 None (예외 없음)."""
    try:
        h = hashlib.sha256()
        pom = cli_dir / "pom.xml"
        if not pom.is_file():
            return None
        h.update(b"pom.xml\0")
        h.update(pom.read_bytes())
        for java in sorted(cli_dir.glob("src/**/*.java")):
            h.update(str(java.relative_to(cli_dir)).replace("\\", "/").encode())
            h.update(b"\0")
            h.update(java.read_bytes())
        return h.hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def match_jar(directory: Path) -> str | None:
    """shaded 우선 jar 매칭 (repo_ast_server._match_jar와 동일 규칙)."""
    patterns = ["*-shaded.jar", "*-jar-with-dependencies.jar", "*.jar"]
    for pattern in patterns:
        matches = sorted(glob.glob(str(directory / pattern)))
        matches = [m for m in matches if not Path(m).name.startswith("original-")]
        if matches:
            return matches[0]
    return None


def status() -> dict:
    dest_dir = data_dir() / DATA_JAR_SUBDIR
    marker = dest_dir / FINGERPRINT_BASENAME
    current = source_fingerprint()
    recorded = None
    if marker.is_file():
        try:
            recorded = marker.read_text(encoding="utf-8").strip() or None
        except OSError:
            recorded = None
    data_jar = match_jar(dest_dir)
    return {
        "sourceFingerprint": current,
        "dataJar": data_jar,
        "recordedFingerprint": recorded,
        "targetJar": match_jar(CLI_DIR / "target"),
        "upToDate": bool(
            data_jar and current and recorded and current == recorded
        ),
    }


def persist() -> dict:
    target_jar = match_jar(CLI_DIR / "target")
    if not target_jar:
        return {
            "status": "failed",
            "error": "TARGET_JAR_NOT_FOUND",
            "message": "mcp/javaparser-cli/target/에 shaded jar가 없다 — "
                       "먼저 ./mvnw -q -DskipTests package로 빌드하라.",
        }
    current = source_fingerprint()
    dest_dir = data_dir() / DATA_JAR_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    # 이전 사본 제거 후 단일 jar 유지(이름이 바뀌어도 잔재가 남지 않도록).
    for old in dest_dir.glob("*.jar"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = dest_dir / Path(target_jar).name
    shutil.copy2(target_jar, dest)
    if current:
        (dest_dir / FINGERPRINT_BASENAME).write_text(current, encoding="utf-8")
    return {
        "status": "ok",
        "persistedJar": str(dest),
        "fingerprint": current,
    }


def main() -> int:
    if "--check" in sys.argv[1:]:
        out = status()
        print(json.dumps(out, ensure_ascii=False))
        return 0
    out = persist()
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
