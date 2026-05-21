#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="/opt/data/home/NewsBriefingsSystem"
PYTHON_BIN="/opt/hermes/.venv/bin/python"
SHADOW_DIR="$PROJECT_ROOT/data/shadow"
LEGACY_ARCHIVE_DIR="/opt/data/home/NewsBriefings"
DATE="$(TZ=Asia/Shanghai date +%F)"
HOUR="$(TZ=Asia/Shanghai date +%H)"

case "$HOUR" in
  08) SLOT="morning"; MANIFEST_HOUR="08" ;;
  13) SLOT="noon"; MANIFEST_HOUR="13" ;;
  20) SLOT="evening"; MANIFEST_HOUR="20" ;;
  *)
    echo "NewsBriefingsSystem shadow cron skipped: unsupported Asia/Shanghai hour '$HOUR' (expected 08, 13, or 20)."
    exit 1
    ;;
esac

cd "$PROJECT_ROOT" || {
  echo "NewsBriefingsSystem shadow cron failed: cannot cd to $PROJECT_ROOT"
  exit 1
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "NewsBriefingsSystem shadow cron failed: python not executable at $PYTHON_BIN"
  exit 1
fi

run_log="$(mktemp)"
compare_log="$(mktemp)"
cleanup() {
  rm -f "$run_log" "$compare_log"
}
trap cleanup EXIT

if ! "$PYTHON_BIN" scripts/run_shadow_briefing.py \
  --slot "$SLOT" \
  --date "$DATE" \
  --shadow-dir "$SHADOW_DIR" >"$run_log" 2>&1; then
  echo "NewsBriefingsSystem shadow run failed for $DATE $SLOT."
  sed -n '1,160p' "$run_log"
  exit 1
fi

manifest="$SHADOW_DIR/data/runs/$DATE-$MANIFEST_HOUR.json"
legacy_archive="$LEGACY_ARCHIVE_DIR/$DATE.md"

if [[ ! -f "$manifest" ]]; then
  echo "NewsBriefingsSystem shadow run failed: manifest not found at $manifest"
  sed -n '1,160p' "$run_log"
  exit 1
fi

if [[ ! -f "$legacy_archive" ]]; then
  echo "NewsBriefingsSystem shadow compare failed: legacy archive not found at $legacy_archive"
  exit 1
fi

if ! "$PYTHON_BIN" scripts/compare_shadow_run.py \
  --legacy-archive "$legacy_archive" \
  --shadow-manifest "$manifest" >"$compare_log" 2>&1; then
  echo "NewsBriefingsSystem shadow compare failed for $DATE $SLOT."
  sed -n '1,160p' "$compare_log"
  exit 1
fi

compare_json="$SHADOW_DIR/reports/$DATE-$MANIFEST_HOUR-compare.json"
if [[ ! -f "$compare_json" ]]; then
  echo "NewsBriefingsSystem shadow compare failed: report not found at $compare_json"
  sed -n '1,160p' "$compare_log"
  exit 1
fi

# Healthy path is intentionally silent. The Python check below only prints on severe drift.
"$PYTHON_BIN" - "$compare_json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
report = json.loads(path.read_text(encoding='utf-8'))
legacy = report['legacy']
shadow = report['shadow']
legacy_count = int(legacy.get('item_count', 0) or 0)
shadow_count = int(shadow.get('item_count', 0) or 0)
legacy_dup = float(legacy.get('duplicate_rate', 0.0) or 0.0)
shadow_dup = float(shadow.get('duplicate_rate', 0.0) or 0.0)
shadow_missing = int(shadow.get('missing_item_ids', {}).get('count', 0) or 0)
shadow_failures = shadow.get('failed_sources', []) or []

issues = []
if legacy_count > 0:
    delta_ratio = abs(shadow_count - legacy_count) / legacy_count
    if delta_ratio >= 0.75:
        issues.append(f'item_count severe drift: legacy={legacy_count}, shadow={shadow_count}, delta_ratio={delta_ratio:.0%}')
elif shadow_count > 0:
    issues.append(f'item_count severe drift: legacy=0, shadow={shadow_count}')

if shadow_dup > max(0.50, legacy_dup + 0.25):
    issues.append(f'duplicate_rate severe drift: legacy={legacy_dup:.1%}, shadow={shadow_dup:.1%}')
if shadow_count and shadow_missing / shadow_count >= 0.50:
    issues.append(f'missing_item_id severe drift: shadow_missing={shadow_missing}/{shadow_count}')
if len(shadow_failures) >= 5:
    issues.append(f'shadow failed_sources unusually high: {len(shadow_failures)}')

if issues:
    print('NewsBriefingsSystem shadow compare found severe drift:')
    for issue in issues:
        print(f'- {issue}')
    print(f'- report={path}')
    sys.exit(2)
PY
