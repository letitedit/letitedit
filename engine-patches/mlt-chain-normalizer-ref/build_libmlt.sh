#!/usr/bin/env bash
# Builds the MLT framework DLL (libmlt-7.dll) alone from MLT commit 63218a28 (the app's 7.41.0) plus
# mlt-chain-normalizer-ref.patch, into $OUT (default <this folder>/../mlt-build/chain-ref/). Nothing is deployed.
#   MLT_SRC  an MLT checkout this script may reset (required: never the shared engine-patches/mlt-build/mlt while
#            another build uses it)
#   STOCK=1  builds it without the patch (the same compiler, for a fair comparison)
# Run with MSYS2's bash under the PC lock, 4 threads:
#   python C:\LetItEdit\bridge\render_lock.py run --name build-t312 -- C:\msys64\usr\bin\bash.exe -lc <this script>
set -euo pipefail
export PATH="/mingw64/bin:$PATH"
git() { "${GIT:-$(command -v git.exe 2>/dev/null || echo '/c/Program Files/Git/cmd/git.exe')}" "$@"; }
here="$(cd "$(dirname "$0")" && pwd)"
mlt="${MLT_SRC:?set MLT_SRC to an MLT checkout of your own}"
variant=patched; [ "${STOCK:-0}" = 1 ] && variant=stock
out="${OUT:-$here/../mlt-build/chain-ref}/$variant"
git -C "$mlt" -c advice.detachedHead=false checkout -q -f --detach 63218a28d21f1e64b5b9e6671b4ff9146023282c
if [ "$variant" = patched ]; then
  tr -d '\r' < "$here/mlt-chain-normalizer-ref.patch" | git -C "$mlt" apply --whitespace=nowarn -
  echo "applied mlt-chain-normalizer-ref.patch"
fi
mkdir -p "$out"
cmake -S "$mlt" -B "$out/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCLANG_FORMAT=OFF -DBUILD_TESTING=OFF \
  -DGPL=ON -DGPL3=ON -DMOD_AVFORMAT=OFF -DMOD_DECKLINK=OFF -DMOD_FREI0R=OFF -DMOD_GDK=OFF -DMOD_GLAXNIMATE=OFF \
  -DMOD_GLAXNIMATE_QT6=OFF -DMOD_JACKRACK=OFF -DMOD_KDENLIVE=OFF -DMOD_MOVIT=OFF -DMOD_NDI=OFF -DMOD_NORMALIZE=OFF \
  -DMOD_OLDFILM=OFF -DMOD_OPENCV=OFF -DMOD_OPENFX=OFF -DMOD_PLACEBO=OFF -DMOD_PLUS=OFF -DMOD_PLUSGPL=OFF -DMOD_QT=OFF \
  -DMOD_QT6=OFF -DMOD_RESAMPLE=OFF -DMOD_RTAUDIO=OFF -DMOD_RUBBERBAND=OFF -DMOD_RNNOISE=OFF -DMOD_SDL1=OFF \
  -DMOD_SDL2=OFF -DMOD_SOX=OFF -DMOD_SPATIALAUDIO=OFF -DMOD_VIDSTAB=OFF -DMOD_VORBIS=OFF -DMOD_XINE=OFF -DMOD_XML=OFF \
  -DMOD_CORE=OFF -DMOD_AVFORMAT=OFF -DSWIG_PYTHON=OFF -DBUILD_DOCS=OFF -DMOD_MELT=OFF \
  > "$out/configure.log" 2>&1 || { tail -30 "$out/configure.log"; exit 1; }
cmake --build "$out/build" --target mlt -j 4 > "$out/build.log" 2>&1 || { tail -40 "$out/build.log"; exit 1; }
dll="$(find "$out/build" -name 'libmlt-7.dll' | head -1)"
cp "$dll" "$out/libmlt-7.dll"
objdump -p "$out/libmlt-7.dll" | grep 'DLL Name' | sort -u
sha256sum "$out/libmlt-7.dll"
