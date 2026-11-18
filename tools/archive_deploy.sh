#!/bin/zsh
# launchd cannot read ~/Desktop (macOS privacy rules), so the scheduled job runs copies from the archive folder.
# Run this after any change to the archive tools.
set -e
D=${AN_ARCHIVE_DIR:-$HOME/factory-scratch/an-archive}/bin
mkdir -p "$D/desk"
cp "${0:A:h}/../desk/airports.py" "$D/desk/airports.py"
for f in archive_lib archive_hourly archive_backfill archive_backup; do
  cp "${0:A:h}/$f.py" "$D/$f.py"
done
print "deployed to $D"
