#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${1:-$ROOT/build/windows/Cyphra}"

CYPHRA_EDITION="${2:-team}"
CYPHRA_COMPANY="Byte Team"
if [[ "$CYPHRA_EDITION" == "public" ]]; then CYPHRA_COMPANY="Cyphra"; fi

ICON="$ROOT/assets/icon.ico"
RCEDIT="${RCEDIT:-$ROOT/tools/rcedit-x64.exe}"

if [ ! -f "$STAGE/runtime/librewolf.exe" ]; then
    echo "ERROR: Windows Gecko engine is missing: $STAGE/runtime/librewolf.exe" >&2
    exit 1
fi

if [ ! -s "$ICON" ]; then
    echo "ERROR: Cyphra icon is missing: $ICON" >&2
    exit 1
fi

if [ ! -s "$RCEDIT" ]; then
    echo "ERROR: rcedit is missing: $RCEDIT" >&2
    exit 1
fi

python3 - "$ROOT/tools-lock.json" "$RCEDIT" <<'VERIFY'
import hashlib, json, pathlib, sys
pin = json.loads(pathlib.Path(sys.argv[1]).read_text())['rcedit']
file = pathlib.Path(sys.argv[2])
if file.is_symlink() or file.stat().st_size != pin['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest() != pin['sha256']:
    raise SystemExit('ERROR: rcedit does not match tools-lock.json; fetch the pinned tool.')
VERIFY

if ! command -v wine >/dev/null; then
    echo "ERROR: wine is required to run rcedit." >&2
    exit 1
fi

ENGINE="$STAGE/runtime/librewolf.exe"

echo "Branding Windows Gecko executable resources:"
echo "  $ENGINE"

WINEDEBUG=-all wine "$RCEDIT" "$ENGINE" \
  --set-icon "$ICON" \
  --set-version-string "CompanyName" "$CYPHRA_COMPANY" \
  --set-version-string "ProductName" "Cyphra" \
  --set-version-string "FileDescription" "Cyphra Gecko Runtime" \
  --set-version-string "InternalName" "Cyphra" \
  --set-version-string "OriginalFilename" "librewolf.exe"

echo "PASS: Windows runtime resources branded as Cyphra."
