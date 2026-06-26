#!/usr/bin/env bash
# run-tests.sh
# Run the narrowest-scope test suite for a given build tool and test pattern.
# Usage: run-tests.sh <buildTool> <testPattern> [projectRoot]
#   buildTool:   "gradle" or "maven"
#   testPattern: JUnit class or method pattern  (e.g. "com.example.FooTest" or "com.example.FooTest#bar")
#   projectRoot: optional; defaults to cwd
# Output: echoes the report directory path on success.
# Exit code: 0 on success, nonzero on build/test failure.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: run-tests.sh <buildTool> <testPattern> [projectRoot]" >&2
  exit 1
fi

BUILD_TOOL="$1"
TEST_PATTERN="$2"
ROOT="${3:-$(pwd)}"

if [ ! -d "$ROOT" ]; then
  echo "ERROR: project root not found: $ROOT" >&2
  exit 1
fi

case "$BUILD_TOOL" in
  gradle)
    if [ -f "$ROOT/gradlew" ]; then
      CMD="$ROOT/gradlew"
    elif command -v gradle >/dev/null 2>&1; then
      CMD="gradle"
    else
      echo "ERROR: neither gradlew nor gradle found" >&2
      exit 1
    fi
    # --no-daemon keeps CI clean; --offline prevents network access
    (cd "$ROOT" && "$CMD" test \
      --tests "$TEST_PATTERN" \
      --no-daemon \
      --offline \
      -x javadoc \
      2>&1)
    REPORT_DIR="$ROOT/build/test-results/test"
    ;;
  maven)
    if [ -f "$ROOT/mvnw" ]; then
      CMD="$ROOT/mvnw"
    elif command -v mvn >/dev/null 2>&1; then
      CMD="mvn"
    else
      echo "ERROR: neither mvnw nor mvn found" >&2
      exit 1
    fi
    # -o = offline; -B = batch (non-interactive)
    (cd "$ROOT" && "$CMD" -B -o test \
      "-Dtest=$TEST_PATTERN" \
      -DfailIfNoTests=false \
      2>&1)
    REPORT_DIR="$ROOT/target/surefire-reports"
    ;;
  *)
    echo "ERROR: unknown build tool: $BUILD_TOOL (expected gradle or maven)" >&2
    exit 1
    ;;
esac

echo "$REPORT_DIR"
