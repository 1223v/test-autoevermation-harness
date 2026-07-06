#!/usr/bin/env python3
"""setup_jdtls.py — Eclipse JDT Language Server provisioner for the harness.

Idempotent, cross-platform (macOS/Linux/Windows), **stdlib only** (no third-party
packages). Resolves a runnable `jdtls` for the plugin's LSP (.lsp.json) in this
order, printing a single line of JSON describing the outcome:

  1. Java 21+ gate  — Eclipse JDT LS "requires a runtime environment of Java 21
     (at a minimum) to run" (eclipse.jdt.ls README). Detected on PATH and via
     $JAVA_HOME. If <21 or missing -> {"status":"failed","reason":"JAVA_21_REQUIRED",...}
     and a nonzero exit; nothing else is attempted.
  2. `jdtls` (or `jdtls.bat` on Windows) already on PATH -> source "path".
  3. A previously provisioned copy under the plugin data dir (marker-gated)
     -> source "provisioned".
  4. macOS + Homebrew: `brew install jdtls`, then re-detect -> source "brew".
  5. Fallback (all OS): download a PINNED JDT LS milestone tarball via urllib,
     extract into <data>/jdtls atomically, mark complete -> source "download".

Usage:
  python3 scripts/setup_jdtls.py                # full provisioning (steps 1-5)
  python3 scripts/setup_jdtls.py --check-only   # detection only (steps 1-3), no install

Exit code is 0 on success ("ok"), nonzero on failure ("failed").

The data dir is resolved the SAME way mcp/launch.cjs and mcp/bootstrap.py do:
env CLAUDE_PLUGIN_DATA, else the <plugin>/mcp/.plugin-data fallback.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# ---------------------------------------------------------------------------
# Pinned JDT LS milestone (verify before bumping)
# Pinned 2026-07-06 to match the current Homebrew `jdtls` formula (v1.60.0).
# Milestone tarballs live under https://download.eclipse.org/jdtls/milestones/<ver>/.
# To bump: pick a newer milestone dir, update all four constants, re-verify sha256.
# ---------------------------------------------------------------------------
JDTLS_VERSION = "1.60.0"
JDTLS_TARBALL = "jdt-language-server-1.60.0-202606262232.tar.gz"
JDTLS_URL = (
    "https://download.eclipse.org/jdtls/milestones/"
    "1.60.0/jdt-language-server-1.60.0-202606262232.tar.gz"
)
JDTLS_SHA256 = "e94c303d8198f977930803582738771fd18c52c5492878410bf222b1aa81ef1d"

# JDT LS requires Java 21+ to RUN (eclipse.jdt.ls README). This is distinct from the
# JDK 17+ needed to BUILD the javaparser-cli jar; both live in this harness.
MIN_JAVA_MAJOR = 21

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(SCRIPT_DIR)
MCP_DIR = os.path.join(PLUGIN_ROOT, "mcp")

IS_WIN = os.name == "nt"


def emit(obj):
    """Print a single line of JSON (the machine-readable contract)."""
    print(json.dumps(obj))


def data_dir():
    """Plugin data dir — mirrors mcp/launch.cjs and mcp/bootstrap.py resolution.

    launch.cjs: process.env.CLAUDE_PLUGIN_DATA || <mcp>/.plugin-data
    bootstrap.py: os.environ["CLAUDE_PLUGIN_DATA"] || <mcp>/.plugin-data
    """
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not d:
        d = os.path.join(MCP_DIR, ".plugin-data")
    return d


def jdtls_bin_name():
    return "jdtls.bat" if IS_WIN else "jdtls"


def provisioned_paths():
    base = os.path.join(data_dir(), "jdtls")
    return (
        base,
        os.path.join(base, "bin", jdtls_bin_name()),
        os.path.join(base, ".setup-complete"),
    )


# ---------------------------------------------------------------------------
# Step 1 — Java 21+ detection
# ---------------------------------------------------------------------------
def _parse_java_major(version_output):
    """Parse the major version from `java -version` output (printed to stderr).

    Handles both the legacy scheme ("1.8.0_292" -> 8) and the modern scheme
    ("17.0.15", "21", "21-ea", "21+35" -> 17 / 21).
    """
    import re

    m = re.search(r'version "([^"]+)"', version_output or "")
    if not m:
        return None
    parts = m.group(1).split(".")
    if parts[0] == "1" and len(parts) > 1:
        head = parts[1]
    else:
        head = parts[0]
    dm = re.match(r"(\d+)", head)
    return int(dm.group(1)) if dm else None


def _java_major(java_exe):
    try:
        r = subprocess.run(
            [java_exe, "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    # `java -version` prints to stderr; fall back to stdout just in case.
    return _parse_java_major(r.stderr or r.stdout)


def detect_java_major():
    """Best (highest) Java major across PATH `java` and $JAVA_HOME/bin/java."""
    candidates = []
    on_path = shutil.which("java")
    if on_path:
        candidates.append(on_path)
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        exe = "java.exe" if IS_WIN else "java"
        candidates.append(os.path.join(java_home, "bin", exe))

    best = None
    for exe in candidates:
        if not exe or (os.path.sep in exe and not os.path.exists(exe)):
            continue
        major = _java_major(exe)
        if major is not None and (best is None or major > best):
            best = major
    return best


# ---------------------------------------------------------------------------
# Steps 2-3 — PATH / provisioned detection
# ---------------------------------------------------------------------------
def jdtls_on_path():
    if shutil.which("jdtls"):
        return True
    if IS_WIN and shutil.which("jdtls.bat"):
        return True
    return False


def jdtls_provisioned():
    _, bin_path, marker = provisioned_paths()
    return os.path.isfile(bin_path) and os.path.isfile(marker)


# ---------------------------------------------------------------------------
# Step 4 — Homebrew (macOS)
# ---------------------------------------------------------------------------
def try_brew_install():
    """Attempt `brew install jdtls` on macOS. Returns True if jdtls lands on PATH."""
    if sys.platform != "darwin" or not shutil.which("brew"):
        return False
    try:
        subprocess.run(
            ["brew", "install", "jdtls"],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except Exception:
        return False
    return jdtls_on_path()


# ---------------------------------------------------------------------------
# Step 5 — pinned tarball download + atomic extract
# ---------------------------------------------------------------------------
def _safe_extract(tar, dest):
    """Extract guarding against path traversal (CVE-2007-4559)."""
    dest_abs = os.path.abspath(dest)
    for member in tar.getmembers():
        target = os.path.abspath(os.path.join(dest, member.name))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise RuntimeError("unsafe path in archive: %s" % member.name)
    tar.extractall(dest)


def download_and_extract():
    """Download the pinned milestone and install it under <data>/jdtls.

    Extraction goes to a temp dir first, then an atomic rename into place, so a
    crash mid-extract never leaves a half-populated <data>/jdtls behind.
    Returns (ok: bool, detail: str).
    """
    base_dir, bin_path, marker = provisioned_paths()
    parent = os.path.dirname(base_dir)
    os.makedirs(parent, exist_ok=True)

    tmp_root = tempfile.mkdtemp(prefix=".jdtls-tmp-", dir=parent)
    try:
        archive = os.path.join(tmp_root, JDTLS_TARBALL)
        # urllib honors HTTPS; download to a temp file, then verify the digest.
        with urllib.request.urlopen(JDTLS_URL, timeout=300) as resp, open(
            archive, "wb"
        ) as out:
            shutil.copyfileobj(resp, out)

        digest = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        got = digest.hexdigest()
        if got != JDTLS_SHA256:
            return False, "sha256 mismatch (expected %s, got %s)" % (JDTLS_SHA256, got)

        extract_dir = os.path.join(tmp_root, "jdtls")
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, extract_dir)

        staged_bin = os.path.join(extract_dir, "bin", jdtls_bin_name())
        if not os.path.isfile(staged_bin):
            return False, "extracted archive missing bin/%s" % jdtls_bin_name()
        if not IS_WIN:
            try:
                os.chmod(staged_bin, os.stat(staged_bin).st_mode | 0o111)
            except Exception:
                pass

        # Atomic swap into place: replace any prior copy, then rename staged in.
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir, ignore_errors=True)
        os.replace(extract_dir, base_dir)

        with open(marker, "w", encoding="utf-8") as f:
            f.write(JDTLS_VERSION + "\n")

        if not os.path.isfile(bin_path):
            return False, "provisioned bin/%s not found after install" % jdtls_bin_name()
        return True, base_dir
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def remediation_cmd():
    launcher = "python" if IS_WIN else "python3"
    return "%s %s" % (launcher, os.path.join("scripts", "setup_jdtls.py"))


def main():
    check_only = "--check-only" in sys.argv[1:]

    # Step 1 — hard Java 21+ gate (JDT LS won't run without it).
    major = detect_java_major()
    if major is None or major < MIN_JAVA_MAJOR:
        emit(
            {
                "status": "failed",
                "reason": "JAVA_21_REQUIRED",
                "detail": "found Java major %s" % (major if major is not None else "none"),
                "remediation": (
                    "Install a JDK 21+ (e.g. `brew install openjdk@21`, or "
                    "https://adoptium.net/) and ensure it is on PATH or set JAVA_HOME."
                ),
            }
        )
        return 1

    # Step 2 — already on PATH.
    if jdtls_on_path():
        emit({"status": "ok", "source": "path"})
        return 0

    # Step 3 — previously provisioned under the plugin data dir.
    if jdtls_provisioned():
        emit({"status": "ok", "source": "provisioned"})
        return 0

    if check_only:
        emit(
            {
                "status": "failed",
                "reason": "JDTLS_NOT_PROVISIONED",
                "remediation": "run: %s" % remediation_cmd(),
            }
        )
        return 1

    # Step 4 — Homebrew on macOS.
    if try_brew_install():
        emit({"status": "ok", "source": "brew"})
        return 0

    # Step 5 — pinned tarball download.
    try:
        ok, detail = download_and_extract()
    except Exception as e:
        emit(
            {
                "status": "failed",
                "reason": "DOWNLOAD_FAILED",
                "detail": str(e),
                "remediation": (
                    "Check network access to %s, or install jdtls manually and put it on PATH."
                    % JDTLS_URL
                ),
            }
        )
        return 1

    if ok:
        emit({"status": "ok", "source": "download"})
        return 0

    emit(
        {
            "status": "failed",
            "reason": "PROVISION_FAILED",
            "detail": detail,
            "remediation": (
                "Install jdtls manually (see %s) and put it on PATH." % JDTLS_URL
            ),
        }
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
