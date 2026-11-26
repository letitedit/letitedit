#!/usr/bin/env bash
# Builds the resample module (libmltresample.dll, in app\lib\mlt) alone from MLT commit 63218a28 (the app's 7.41.0)
# plus mlt-resample-close.patch, into $OUT (default <this folder>/../mlt-build/resample-close/). Nothing is deployed.
# The framework patches (mlt-chain-normalizer-ref, mlt-cache-held-item) are applied too, so the libmlt-7.dll built
# beside it is the same source as ../mlt-cache-held-item/build_libmlt.sh's "both" (the module only links to it).
#   MLT_SRC   an MLT checkout this script may reset (required: never the shared engine-patches/mlt-build/mlt while
#             another build uses it)
#   STOCK=1   builds the module without mlt-resample-close.patch (the same compiler, for a fair comparison)
# Needs MSYS2's mingw-w64-x86_64-libsamplerate (samplerate.pc). Run with MSYS2's bash under the PC lock, 4 threads:
#   python C:\LetItEdit\bridge\render_lock.py run --name build-t315 -- C:\msys64\usr\bin\bash.exe -lc <this script>
set -euo pipefail
export PATH="/mingw64/bin:$PATH"
git() { "${GIT:-$(command -v git.exe 2>/dev/null || echo '/c/Program Files/Git/cmd/git.exe')}" "$@"; }
here="$(cd "$(dirname "$0")" && pwd)"
mlt="${MLT_SRC:?set MLT_SRC to an MLT checkout of your own}"
variant=patched; [ "${STOCK:-0}" = 1 ] && variant=stock
out="${OUT:-$here/../mlt-build/resample-close}/$variant"
git -C "$mlt" -c advice.detachedHead=false checkout -q -f --detach 63218a28d21f1e64b5b9e6671b4ff9146023282c
patches=("$here/../mlt-chain-normalizer-ref/mlt-chain-normalizer-ref.patch" "$here/../mlt-cache-held-item/mlt-cache-held-item.patch")
[ "$variant" = patched ] && patches+=("$here/mlt-resample-close.patch")
for p in "${patches[@]}"; do
  tr -d '\r' < "$p" | git -C "$mlt" apply --whitespace=nowarn -
  echo "applied $(basename "$p")"
done
# keep this PC's folders out of the binaries (__FILE__ in the engine's messages): the source shows as mlt/...
mapflags="-ffile-prefix-map=$(cygpath -m "$mlt")=mlt"
mkdir -p "$out"
cmake -S "$mlt" -B "$out/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS="$mapflags" -DCMAKE_CXX_FLAGS="$mapflags" -DCLANG_FORMAT=OFF -DBUILD_TESTING=OFF \
  -DGPL=ON -DGPL3=ON -DMOD_AVFORMAT=OFF -DMOD_DECKLINK=OFF -DMOD_FREI0R=OFF -DMOD_GDK=OFF -DMOD_GLAXNIMATE=OFF \
  -DMOD_GLAXNIMATE_QT6=OFF -DMOD_JACKRACK=OFF -DMOD_KDENLIVE=OFF -DMOD_MOVIT=OFF -DMOD_NDI=OFF -DMOD_NORMALIZE=OFF \
  -DMOD_OLDFILM=OFF -DMOD_OPENCV=OFF -DMOD_OPENFX=OFF -DMOD_PLACEBO=OFF -DMOD_PLUS=OFF -DMOD_PLUSGPL=OFF -DMOD_QT=OFF \
  -DMOD_QT6=OFF -DMOD_RESAMPLE=ON -DMOD_RTAUDIO=OFF -DMOD_RUBBERBAND=OFF -DMOD_RNNOISE=OFF -DMOD_SDL1=OFF \
  -DMOD_SDL2=OFF -DMOD_SOX=OFF -DMOD_SPATIALAUDIO=OFF -DMOD_VIDSTAB=OFF -DMOD_VORBIS=OFF -DMOD_XINE=OFF -DMOD_XML=OFF \
  -DMOD_CORE=OFF -DSWIG_PYTHON=OFF -DBUILD_DOCS=OFF -DMOD_MELT=OFF \
  > "$out/configure.log" 2>&1 || { tail -30 "$out/configure.log"; exit 1; }
cmake --build "$out/build" --target mltresample -j 4 > "$out/build.log" 2>&1 || { tail -40 "$out/build.log"; exit 1; }
dll="$(find "$out/build" -name 'libmltresample.dll' | head -1)"
cp "$dll" "$out/libmltresample.dll"
objdump -p "$out/libmltresample.dll" | grep 'DLL Name' | sort -u
sha256sum "$out/libmltresample.dll"
