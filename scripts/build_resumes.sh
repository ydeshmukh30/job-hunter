#!/usr/bin/env bash
# Compile the six LaTeX resume variants to PDF.
#
# Auto-apply uploads a PDF.  The variants live as .tex sources only, so without
# this step every auto-apply attempt fails at the upload.
#
# tectonic over MacTeX deliberately: one self-contained binary that fetches only
# the packages a document actually uses, vs a multi-GB TeX Live install.
set -euo pipefail

SRC="${HOME}/Desktop/cognizant/interview/resumes/tex"
OUT="${HOME}/Desktop/cognizant/interview/resumes/pdf"

if ! command -v tectonic >/dev/null 2>&1; then
  echo "tectonic not found. Install it with:" >&2
  echo "    brew install tectonic" >&2
  exit 1
fi

if [ ! -d "$SRC" ]; then
  echo "LaTeX sources not found at $SRC" >&2
  exit 1
fi

mkdir -p "$OUT"

built=0
failed=0
for tex in "$SRC"/*.tex; do
  [ -e "$tex" ] || continue
  name="$(basename "$tex" .tex)"
  printf '  %-32s ' "$name"
  if tectonic --outdir "$OUT" --chatter minimal "$tex" >/dev/null 2>&1; then
    echo "ok"
    built=$((built + 1))
  else
    echo "FAILED"
    failed=$((failed + 1))
  fi
done

echo
echo "built: $built   failed: $failed   -> $OUT"
[ "$failed" -eq 0 ]
