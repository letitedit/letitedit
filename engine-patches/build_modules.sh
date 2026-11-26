#!/usr/bin/env bash
# Builds letitedit's two patched MLT modules (engine-patches/README.md) from MLT commit 63218a28 (the source of the
# app's MLT 7.41.0) plus the patches in this folder:
#   libmltqt6.dll   mlt-qtext-fontdirs (LETITEDIT_FONT_DIRS) + mlt-qtext-weight (bold and other weights)
#   libmltplus.dll  mlt-subtitle-feed-range (a caption that runs to the video's end is drawn)
# into engine-patches/modules/ with SHA256SUMS.txt. Deploy them with deploy.ps1; check them with check_engine.py.
#
# Run with MSYS2's bash (it puts MINGW64's tools first itself; packages: mingw-w64-x86_64-gcc, cmake, ninja,
# pkgconf, qt6-base, qt6-svg, fftw, libexif), under the PC lock:
#   python C:\LetItEdit\bridge\render_lock.py run --name engine-modules -- ^
#     C:\msys64\usr\bin\bash.exe -lc /c/LetItEdit/engine-patches/build_modules.sh
#
# MLT_SRC  an MLT git checkout this script may reset (default engine-patches/mlt-build/mlt). To make one:
#            git clone https://github.com/mltframework/mlt.git
#            git -C mlt checkout 63218a28d21f1e64b5b9e6671b4ff9146023282c
# JOBS     build threads (default 4, the PC's cap)
# STOCK=1  builds the same modules without the patches into mlt-build/stock-modules/ (for comparisons)
# MODULES  which to build: "qt6 plus" (default), "qt6" or "plus"
#
# The text module links FFTW and libexif statically and the plus module links libfftw3-3.dll, as the shipped Shotcut
# 26.9.27 modules do, so both import exactly the DLLs the app already has (the script prints the import tables).
set -euo pipefail
export PATH="/mingw64/bin:$PATH"
export GIT_NO_LAZY_FETCH=1   # a partial clone must never download behind our back
# MSYS2 has no git of its own on this PC: use Git for Windows unless GIT names another
git() { "${GIT:-$(command -v git.exe 2>/dev/null || echo '/c/Program Files/Git/cmd/git.exe')}" "$@"; }
here="$(cd "$(dirname "$0")" && pwd)"
mlt="${MLT_SRC:-$here/mlt-build/mlt}"
jobs="${JOBS:-4}"
commit=63218a28d21f1e64b5b9e6671b4ff9146023282c
if [ "${STOCK:-0}" = 1 ]; then variant=stock out="$here/mlt-build/stock-modules"; else variant=patched out="$here/modules"; fi
work="$here/mlt-build/build/$variant"

# 1. the source: MLT at the app's commit, then the patches (CR stripped: the repo checks them out with CRLF)
git -C "$mlt" -c advice.detachedHead=false checkout -q -f --detach "$commit"
if [ "${STOCK:-0}" != 1 ]; then
  for p in mlt-qtext-fontdirs/mlt-qt-fontdirs.patch mlt-qtext-weight/mlt-qtext-weight.patch \
           mlt-subtitle-feed-range/mlt-subtitle-feed-range.patch; do
    tr -d '\r' < "$here/$p" | git -C "$mlt" apply --whitespace=nowarn -
    echo "applied $p"
  done
fi

# 2. configure and build one module per build folder
off="-DMOD_AVFORMAT=OFF -DMOD_DECKLINK=OFF -DMOD_FREI0R=OFF -DMOD_GDK=OFF -DMOD_GLAXNIMATE_QT6=OFF -DMOD_JACKRACK=OFF
  -DMOD_KDENLIVE=OFF -DMOD_MOVIT=OFF -DMOD_NDI=OFF -DMOD_NORMALIZE=OFF -DMOD_OLDFILM=OFF -DMOD_OPENCV=OFF
  -DMOD_OPENFX=OFF -DMOD_PLACEBO=OFF -DMOD_PLUSGPL=OFF -DMOD_RESAMPLE=OFF -DMOD_RTAUDIO=OFF -DMOD_RUBBERBAND=OFF
  -DMOD_RNNOISE=OFF -DMOD_SDL1=OFF -DMOD_SDL2=OFF -DMOD_SOX=OFF -DMOD_SPATIALAUDIO=OFF -DMOD_VIDSTAB=OFF
  -DMOD_VORBIS=OFF -DMOD_XINE=OFF -DMOD_XML=OFF"
# keep this PC's folders out of the binaries (__FILE__ in the engine's messages): the source shows as mlt/...
mapflags="-ffile-prefix-map=$(cygpath -m "$mlt")=mlt"
build() {  # build <folder> <target> <extra cmake args...>
  local dir="$work/$1" target="$2"; shift 2
  # shellcheck disable=SC2086
  cmake -S "$mlt" -B "$dir" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS="$mapflags" -DCMAKE_CXX_FLAGS="$mapflags" -DCLANG_FORMAT=OFF -DBUILD_TESTING=OFF -DGPL=ON \
    -DGPL3=ON $off "$@" > "$dir.configure.log" 2>&1 || { tail -30 "$dir.configure.log"; exit 1; }
  cmake --build "$dir" --target "$target" -j "$jobs" > "$dir.build.log" 2>&1 || { tail -40 "$dir.build.log"; exit 1; }
}
modules="${MODULES:-qt6 plus}"
mkdir -p "$work" "$out"
case " $modules " in *" qt6 "*)
  build qt6 mltqt6 -DMOD_QT6=ON -DMOD_PLUS=OFF -DCMAKE_FIND_LIBRARY_SUFFIXES=.a
  cp "$work/qt6/out/lib/mlt/libmltqt6.dll" "$out/" ;;
esac
case " $modules " in *" plus "*)
  build plus mltplus -DMOD_QT6=OFF -DMOD_PLUS=ON
  cp "$work/plus/out/lib/mlt/libmltplus.dll" "$out/" ;;
esac

# 3. the modules' checksums and import tables
(cd "$out" && sha256sum libmlt*.dll > SHA256SUMS.txt && cat SHA256SUMS.txt)
for m in "$out"/libmlt*.dll; do
  echo "$(basename "$m") imports: $(objdump -p "$m" | sed -n 's/^\s*DLL Name: //p' | tr '\n' ' ')"
done
git -C "$mlt" log --oneline -1
