#!/usr/bin/env bash
# Extract the human-readable strings from the original module .so.
# Used to seed reverse_engineering/strings_dump.txt.
set -euo pipefail
in="${1:-reverse_engineering/original_arm64-v8a.so}"
out="${2:-reverse_engineering/strings_dump.txt}"
strings -n 8 "$in" > "$out"
echo "$(wc -l < "$out") strings -> $out"
