#!/usr/bin/env bash
# Builds a minimal static FFmpeg for DiscTag (WAV in -> FLAC / MP3 out).
# Usage: bash scripts/build_ffmpeg.sh [output_dir]
set -euo pipefail

FFMPEG_VERSION=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e

OUT_DIR="${1:-${OUTPUT_DIR:-$PWD/ffmpeg-bin}}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PREFIX="$WORK/prefix"
mkdir -p "$PREFIX"

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) PLATFORM=windows; EXE=ffmpeg.exe ;;
    Darwin*)              PLATFORM=macos;   EXE=ffmpeg ;;
    *)                    PLATFORM=linux;   EXE=ffmpeg ;;
esac
if [ "$PLATFORM" != "macos" ] && [ "$PLATFORM" != "windows" ]; then
    echo "This script supports MSYS2 UCRT64 and macOS only." >&2
    exit 1
fi
if [ "$PLATFORM" = "macos" ]; then
    export MACOSX_DEPLOYMENT_TARGET=11.0
fi
JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)

verify_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        echo "$2  $1" | sha256sum -c - >/dev/null
    else
        echo "$2  $1" | shasum -a 256 -c - >/dev/null
    fi
}

fetch() {
    local name="$1" url="$2" sha256="$3"
    curl -fL --retry 5 --retry-all-errors --retry-delay 5 -o "$WORK/$name" "$url"
    verify_sha256 "$WORK/$name" "$sha256"
}

cd "$WORK"
fetch "lame-$LAME_VERSION.tar.gz" \
    "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
    "$LAME_SHA256"
fetch "ffmpeg-$FFMPEG_VERSION.tar.xz" \
    "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
    "$FFMPEG_SHA256"
tar xf "lame-$LAME_VERSION.tar.gz"
tar xf "ffmpeg-$FFMPEG_VERSION.tar.xz"

echo "=== Building LAME $LAME_VERSION (static) ==="
cd "$WORK/lame-$LAME_VERSION"
if ! ./config.guess >/dev/null 2>&1; then
    curl -fsSL -o config.guess "https://git.savannah.gnu.org/cgit/config.git/plain/config.guess"
    curl -fsSL -o config.sub "https://git.savannah.gnu.org/cgit/config.git/plain/config.sub"
    chmod +x config.guess config.sub
fi
LAME_CFLAGS=""
if [ "$PLATFORM" = "macos" ]; then
    LAME_CFLAGS="-Wno-implicit-function-declaration"
fi
CFLAGS="$LAME_CFLAGS" ./configure \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    --disable-frontend --disable-decoder
make -j"$JOBS"
make install

echo "=== Building FFmpeg $FFMPEG_VERSION (minimal, LGPL) ==="
cd "$WORK/ffmpeg-$FFMPEG_VERSION"
EXTRA_LDFLAGS="-L$PREFIX/lib"
if [ "$PLATFORM" = "windows" ]; then
    EXTRA_LDFLAGS="$EXTRA_LDFLAGS -static"
fi
./configure \
    --prefix="$WORK/ffmpeg-install" \
    --disable-everything \
    --disable-autodetect \
    --disable-network \
    --disable-doc \
    --disable-debug \
    --disable-ffplay \
    --disable-ffprobe \
    --disable-avdevice \
    --disable-swscale \
    --enable-static \
    --disable-shared \
    --enable-ffmpeg \
    --enable-libmp3lame \
    --enable-protocol=file,pipe \
    --enable-demuxer=wav \
    --enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,pcm_u8 \
    --enable-encoder=flac,libmp3lame \
    --enable-muxer=flac,mp3 \
    --enable-filter=abuffer,abuffersink,aformat,anull,aresample \
    --extra-cflags="-I$PREFIX/include" \
    --extra-ldflags="$EXTRA_LDFLAGS"
make -j"$JOBS"

cp "$EXE" "$OUT_DIR/$EXE"
strip "$OUT_DIR/$EXE"

echo "=== Result ==="
"$OUT_DIR/$EXE" -version | head -3
ls -la "$OUT_DIR/$EXE"

if [ "$PLATFORM" = "windows" ]; then
    echo "=== Linked DLLs ==="
    objdump -p "$OUT_DIR/$EXE" | grep "DLL Name" | awk '{print $3}' | sort -u | tee "$WORK/dlls.txt"
    BAD=$(grep -viE '^(api-ms-win-(crt|core)-.*|KERNEL32|msvcrt|ADVAPI32|USER32|WS2_32|GDI32|ole32|OLEAUT32|SHELL32|IMM32|COMDLG32|COMCTL32|bcrypt|SHLWAPI|WINMM|IPHLPAPI|ntdll|RPCRT4|Secur32|SSPICLI|VERSION|AVRT|powrprof|dbghelp|SETUPAPI|CRYPT32|MFPlat|MF|MFUUID|evr|dxva2|msdmo|QUARTZ|STRMIIDS|Normaliz|WLDAP32|NETAPI32|COMBASE|OLEACC|USP10|kernel.appcore)\.dll$' "$WORK/dlls.txt" || true)
else
    echo "=== Linked libraries ==="
    otool -L "$OUT_DIR/$EXE" | tee "$WORK/dlls.txt"
    BAD=$(grep -vE '^\s*(/usr/lib/libSystem\.B\.dylib|/System/Library/|@rpath/' "$WORK/dlls.txt" | grep -v "$EXE:" || true)
fi
if [ -n "${BAD:-}" ]; then
    echo "ERROR: binary links non-system libraries:" >&2
    echo "$BAD" >&2
    exit 1
fi
echo "OK: $OUT_DIR/$EXE links system libraries only."
