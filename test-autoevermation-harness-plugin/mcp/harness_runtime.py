"""Shared runtime diagnostics; no provisioning or project writes on import."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def data_dir() -> Path:
    key = "PLUGIN_DATA" if os.environ.get("HARNESS_HOST") == "codex" else "CLAUDE_PLUGIN_DATA"
    value = os.environ.get(key) or os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(value).resolve() if value else Path(__file__).resolve().parent / ".plugin-data"


def runtime_info() -> dict:
    location = data_dir()
    ancestor = location
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    from importlib.metadata import version, PackageNotFoundError
    try:
        sdk = version("mcp")
    except PackageNotFoundError:
        sdk = None
    return {"host": os.environ.get("HARNESS_HOST", "claude"),
            "pluginRoot": str(Path(__file__).resolve().parent.parent),
            "pluginData": str(data_dir()), "pythonExecutable": sys.executable,
            "pythonVersion": sys.version.split()[0], "sdkVersion": sdk,
            "dataExplicit": bool(os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")),
            "dataWritableHint": os.access(ancestor, os.W_OK),
            "dataPathLength": len(str(location)),
            "dataWarnings": ["WINDOWS_LONG_DATA_PATH: configure a shorter official host location if provisioning/import fails"]
                            if os.name == "nt" and len(str(location)) > 170 else []}


def scoped_path(root: str, value: str) -> Path:
    base = Path(root).resolve()
    path = Path(value)
    path = (path if path.is_absolute() else base / path).resolve()
    if not path.is_relative_to(base):
        raise ValueError("PROJECT_PATH_DENIED: " + str(path))
    return path


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def persisted_jar_state(directory: Path) -> dict | None:
    """The manifest is the atomic commit point for jar + source/digest metadata."""
    try:
        state = json.loads((directory / "astcli-state.json").read_text(encoding="utf-8"))
        jar = (directory / state["jar"]).resolve()
        if jar.parent != directory.resolve() or file_digest(jar) != state["sha256"]:
            return None
        import zipfile
        if not zipfile.is_zipfile(jar):
            return None
        return dict(state, path=str(jar))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".harness-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stop_process_tree(process: subprocess.Popen) -> None:
    """Only terminate the still-running child owned by this caller."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
