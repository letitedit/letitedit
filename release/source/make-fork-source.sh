#!/usr/bin/env bash
# Produces the complete corresponding source of the letitedit editor fork as built, locally (nothing is pushed or
# uploaded). Run in Git Bash:   bash /c/LetItEdit/release/source/make-fork-source.sh [out_dir]
#
# Output (default C:\LetItEdit\release\source\out\<yyyymmdd-HHMMSS>\):
#   letitedit-fork-src.tar.gz       full source tree = upstream mltframework/shotcut at UPSTREAM_COMMIT + local changes
#                                    (tracked edits and new files; .gitignore'd build output left out)
#   letitedit-fork.patch            the local changes as one git patch (binary-safe) against UPSTREAM_COMMIT
#   letitedit-fork-files.txt        files the patch touches
#   mlt-63218a28-letitedit-src.tar.gz  MLT source as built for app\lib\mlt\libmltqt6.dll, libmltplus.dll and
#                                    app\libmlt-7.dll (upstream + the six patches)
#   mlt-patches\                     0001-mlt-qt-fontdirs.patch, 0002-mlt-qtext-weight.patch,
#                                    0003-mlt-subtitle-feed-range.patch, 0004-mlt-chain-normalizer-ref.patch,
#                                    0005-mlt-cache-held-item.patch, 0006-mlt-resample-close.patch
#   BUILD.txt                        how the editor exe and the patched MLT modules were built
#   SHA256SUMS.txt
# Read-only for C:\LetItEdit\src and engine-patches: the fork's git index and objects are not touched (a temporary
# index and object directory are used).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC=/c/LetItEdit/src
MLT_GIT=/c/LetItEdit/engine-patches/mlt-build/mlt   # an MLT clone holding commit MLT_COMMIT
UPSTREAM_COMMIT=325c2cc6422d93567d4edb57f1fee401f73beea1
MLT_COMMIT=63218a28d21f1e64b5b9e6671b4ff9146023282c
OUT="${1:-$HERE/out/$(date +%Y%m%d-%H%M%S)}"
if [ -e "$OUT" ]; then echo "$OUT exists; choose another folder" >&2; exit 1; fi
mkdir -p "$OUT/mlt-patches"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- the fork ------------------------------------------------------------------------------------------------
[ "$(git -C "$SRC" rev-parse HEAD)" = "$UPSTREAM_COMMIT" ] || { echo "src HEAD is not $UPSTREAM_COMMIT" >&2; exit 1; }
export GIT_INDEX_FILE="$TMP/index" GIT_OBJECT_DIRECTORY="$TMP/objects" GIT_ALTERNATE_OBJECT_DIRECTORIES="$SRC/.git/objects"
mkdir -p "$TMP/objects"
git -C "$SRC" read-tree HEAD
git -C "$SRC" add -A .          # tracked edits + untracked files not ignored by .gitignore
TREE=$(git -C "$SRC" write-tree)
git -C "$SRC" diff-tree -r --binary -p --full-index "$UPSTREAM_COMMIT" "$TREE" > "$OUT/letitedit-fork.patch"
git -C "$SRC" diff-tree -r --name-status "$UPSTREAM_COMMIT" "$TREE" > "$OUT/letitedit-fork-files.txt"
git -C "$SRC" archive --format=tar.gz --prefix=letitedit-fork/ -o "$OUT/letitedit-fork-src.tar.gz" "$TREE"
unset GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES

# --- MLT qt and plus modules and the framework as built (fonts + weight, captions to the end, clip links freed) ---
cp "$HERE/mlt-patches/0001-mlt-qt-fontdirs.patch" "$HERE/mlt-patches/0002-mlt-qtext-weight.patch" \
   "$HERE/mlt-patches/0003-mlt-subtitle-feed-range.patch" "$HERE/mlt-patches/0004-mlt-chain-normalizer-ref.patch" \
   "$HERE/mlt-patches/0005-mlt-cache-held-item.patch" "$HERE/mlt-patches/0006-mlt-resample-close.patch" \
   "$OUT/mlt-patches/"
export GIT_NO_LAZY_FETCH=1   # engine-patches/mlt-build/mlt is a partial clone: never download behind our back
git clone -q --no-checkout "$MLT_GIT" "$TMP/mlt"
git -C "$TMP/mlt" -c advice.detachedHead=false -c core.autocrlf=false checkout -q "$MLT_COMMIT"
# (line endings stripped: a Windows checkout may hold the patch files with CRLF, which git apply refuses)
for p in 0001-mlt-qt-fontdirs 0002-mlt-qtext-weight 0003-mlt-subtitle-feed-range 0004-mlt-chain-normalizer-ref 0005-mlt-cache-held-item 0006-mlt-resample-close; do
  tr -d '\r' < "$OUT/mlt-patches/$p.patch" | git -C "$TMP/mlt" apply --whitespace=nowarn -
done
rm -rf "$TMP/mlt/.git"
tar -C "$TMP" -czf "$OUT/mlt-63218a28-letitedit-src.tar.gz" --transform 's,^mlt,mlt-63218a28-letitedit,' mlt

cp "$HERE/BUILD.txt" "$OUT/BUILD.txt"
( cd "$OUT" && find . -type f ! -name SHA256SUMS.txt -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.txt )
echo "Wrote $OUT"
ls -la "$OUT"
