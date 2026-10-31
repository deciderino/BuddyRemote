#!/bin/bash
# Build the Windows zip on Linux with Wine + a Windows Python (cross build).
# Env: WINEPREFIX with Windows Python + pyinstaller/PyQt6/PySDL2/pysdl2-dll installed,
#      WINPY='C:\Python313\python.exe' (default),
#      MOONDECK_CLI=/path/to/moondeck-cli-win.exe, MOONDECK_CLI_SHA256=<sha> (required).
# Natively on Windows run packaging\windows\build.py directly (see its docstring).
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${MOONDECK_CLI:?set MOONDECK_CLI}"; : "${MOONDECK_CLI_SHA256:?set MOONDECK_CLI_SHA256}"
WINPY="${WINPY:-C:\\Python313\\python.exe}"
echo "$MOONDECK_CLI_SHA256  $MOONDECK_CLI" | sha256sum -c -
wine "$WINPY" "$(winepath -w packaging/windows/build.py)" \
  --cli "$(winepath -w "$MOONDECK_CLI")" --sha256 "$MOONDECK_CLI_SHA256" \
  --cli-version "${MOONDECK_CLI_VERSION:-nightly}" --cli-commit "${MOONDECK_CLI_COMMIT:-00f8c31}" \
  --buddy-api "${MOONDECK_CLI_BUDDY_API:-9}"
