#!/usr/bin/env bash
# detect-build-tool.sh
# Detect whether a project root uses Gradle or Maven as its build tool.
# Usage: detect-build-tool.sh [project-root]
# Output: JSON {"buildTool":"gradle|maven|none","wrapper":bool}
# Exit code: 0 on success, 1 if no build tool detected.
set -euo pipefail

ROOT="${1:-$(pwd)}"

if [ ! -d "$ROOT" ]; then
  echo "ERROR: directory not found: $ROOT" >&2
  exit 1
fi

TOOL="none"
WRAPPER=false

# Gradle detection: prefer wrapper, then standard build files
if [ -f "$ROOT/gradlew" ]; then
  TOOL="gradle"
  WRAPPER=true
elif [ -f "$ROOT/build.gradle" ] || [ -f "$ROOT/build.gradle.kts" ]; then
  TOOL="gradle"
  WRAPPER=false
# Maven detection: prefer wrapper, then pom.xml
elif [ -f "$ROOT/mvnw" ]; then
  TOOL="maven"
  WRAPPER=true
elif [ -f "$ROOT/pom.xml" ]; then
  TOOL="maven"
  WRAPPER=false
fi

if [ "$TOOL" = "none" ]; then
  echo "BUILD_TOOL_UNDETECTED: no Gradle or Maven build files found in: $ROOT" >&2
  exit 1
fi

# Emit JSON using printf to avoid any locale/quoting issues
printf '{"buildTool":"%s","wrapper":%s}\n' "$TOOL" "$WRAPPER"
