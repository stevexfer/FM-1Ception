#!/bin/bash
# FM-1Ception Linux archives — Xfer Records
#
# Release build + one .zip per architecture (VST3 bundle, standalone, LICENSE, INSTALL.txt).
# Run inside the Ubuntu VM (or any Debian/Ubuntu box with cmake, ninja, Rust, and the JUCE
# dev libraries). Builds the host's architecture natively; the other arch uses
# fm1ception/cmake/toolchains/linux-*.cmake when the cross compiler is installed.
#
# Usage:
#   installer/linux/build_packages.sh [--arch amd64|arm64|all] [--skip-build]
#
# Environment overrides:
#   FM1C_BUILD_DIR   build root (default /var/tmp/fm1ception-build). Keep it off the
#                      Parallels share: compiling on /media/psf is much slower.
set -euo pipefail
umask 022

ARCHES="all"
SKIP_BUILD=0
while [ $# -gt 0 ]; do
    case "$1" in
        --arch) ARCHES="$2"; shift 2 ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        *) echo "Unknown option: $1"; echo "Usage: $0 [--arch amd64|arm64|all] [--skip-build]"; exit 1 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/Installers"
BUILD_ROOT="${FM1C_BUILD_DIR:-${HOME}/fm1ception-build}"
LABEL="$(tr -d '\r' < "$ROOT/installer/label.txt")"
[ -n "$LABEL" ] || { echo "ERROR: empty installer/label.txt"; exit 1; }
HOST_ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

case "$HOST_ARCH" in
    amd64) HOST_ARCH=amd64 ;;
    arm64|aarch64) HOST_ARCH=arm64 ;;
esac

if [ "$ARCHES" = "all" ]; then
    # The host's arch first: on an arm64 VM amd64 may be cross-only and can fail without extra packages.
    [ "$HOST_ARCH" = arm64 ] && ARCHES="arm64 amd64" || ARCHES="amd64 arm64"
fi

install_deps() {
    command -v apt-get >/dev/null 2>&1 || return 0
  if ! pkg-config --exists libcurl 2>/dev/null || ! pkg-config --exists alsa 2>/dev/null; then
        echo "Installing build dependencies (sudo)..."
        sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            build-essential pkg-config cmake ninja-build git curl ca-certificates zip \
            libasound2-dev libcurl4-openssl-dev libfontconfig1-dev libfreetype-dev \
            libx11-dev libxcomposite-dev libxcursor-dev libxext-dev libxinerama-dev \
            libxi-dev libxrandr-dev libxrender-dev libgl-dev libjack-jackd2-dev
    fi
}

echo "========================================="
echo "Building FM-1Ception $LABEL Linux packages"
echo "========================================="
echo "Host: $HOST_ARCH, $JOBS jobs; targets: $ARCHES"
install_deps
mkdir -p "$OUT" "$BUILD_ROOT"
if ! command -v cargo >/dev/null 2>&1; then
    if [ -x "${HOME}/.cargo/bin/cargo" ]; then
        export PATH="${HOME}/.cargo/bin:${PATH}"
    else
        echo "Rust not found; installing a minimal toolchain..."
        curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
        # shellcheck disable=SC1090
        [ -f "${HOME}/.cargo/env" ] && . "${HOME}/.cargo/env"
        export PATH="${HOME}/.cargo/bin:${PATH}"
    fi
else
    export PATH="${HOME}/.cargo/bin:${PATH}"
fi

gnu_triple() { case "$1" in amd64) echo x86_64-linux-gnu ;; arm64) echo aarch64-linux-gnu ;; esac; }
rust_target_for() { case "$1" in amd64) echo x86_64-unknown-linux-gnu ;; arm64) echo aarch64-unknown-linux-gnu ;; esac; }
toolchain_for() { case "$1" in amd64) echo linux-x86_64 ;; arm64) echo linux-aarch64 ;; esac; }
zip_arch() { case "$1" in amd64) echo x86_64 ;; arm64) echo arm64 ;; esac; }

ensure_rust_target() {
    local arch="$1" rt
    rt="$(rust_target_for "$arch")"
    rustup target list --installed | grep -q "^${rt}$" || rustup target add "$rt"
}

build_arch() {
    local arch="$1" bdir="$BUILD_ROOT/$arch"
    local args=(-S "$ROOT" -B "$bdir" -G Ninja -DCMAKE_BUILD_TYPE=Release)
    if [ "$arch" != "$HOST_ARCH" ]; then
        local tc="$ROOT/cmake/toolchains/$(toolchain_for "$arch").cmake"
        local gxx
        gxx="$(gnu_triple "$arch")-g++"
        if [ ! -f "$tc" ] || ! command -v "$gxx" >/dev/null 2>&1; then
            echo "SKIP $arch: no cross toolchain ($gxx / $(basename "$tc"))"
            return 2
        fi
        ensure_rust_target "$arch"
        args+=(-DCMAKE_TOOLCHAIN_FILE="$tc")
    fi
    echo ""
    echo "--- Configuring $arch in $bdir"
    cmake "${args[@]}"
    echo "--- Building $arch"
    cmake --build "$bdir" -j"$JOBS"
}

package_arch() {
    local arch="$1" bdir="$BUILD_ROOT/$arch"
    local dist="$BUILD_ROOT/dist/FM-1Ception_${LABEL}_Linux_$(zip_arch "$arch")"
    local vst3="$bdir/FM1Ception_artefacts/Release/VST3/FM-1Ception.vst3"
    local bin="$bdir/FM1Ception_artefacts/Release/Standalone/FM-1Ception"
    [ -d "$vst3" ] || { echo "ERROR: $vst3 not found"; return 1; }
    [ -f "$bin" ] || { echo "ERROR: $bin not found"; return 1; }

    local strip="strip"
    if [ "$arch" != "$HOST_ARCH" ]; then
        strip="$(gnu_triple "$arch")-strip"
    fi

    rm -rf "$dist"
    mkdir -p "$dist"
    cp -R "$vst3" "$dist/"
    install -m755 "$bin" "$dist/FM-1Ception"
    install -m644 "$ROOT/LICENSE" "$dist/"
    cat > "$dist/INSTALL.txt" <<'EOF'
FM-1Ception for Linux

VST3:       copy FM-1Ception.vst3 into ~/.vst3/ (or /usr/lib/vst3/ for everyone)
Standalone: run ./FM-1Ception from this folder

Needs glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora 36, Arch and newer), ALSA,
FreeType, Fontconfig and X11. The Cloud tab also needs libcurl (libcurl.so.4).
EOF
    "$strip" --strip-unneeded "$dist/FM-1Ception" 2>/dev/null || true
    local so
    so="$(find "$dist/FM-1Ception.vst3" -name 'FM-1Ception.so' | head -1)"
    [ -n "$so" ] && "$strip" --strip-unneeded "$so" 2>/dev/null || true

    echo "--- $arch links against (standalone):"
    readelf -d "$dist/FM-1Ception" | sed -n 's/.*NEEDED.*\[\(.*\)\]/    \1/p' || true

    local zip="$OUT/Install_FM-1Ception_${LABEL}_Linux_$(zip_arch "$arch").zip"
    rm -f "$zip"
    (cd "$BUILD_ROOT/dist" && zip -rq "$zip" "$(basename "$dist")")
    echo "Created $zip"
}

BUILT=()
SKIPPED=()
for arch in $ARCHES; do
    rc=0
    if [ "$SKIP_BUILD" = 0 ]; then
        build_arch "$arch" || rc=$?
    fi
    if [ "$rc" = 2 ]; then SKIPPED+=("$arch"); continue; fi
    [ "$rc" = 0 ] || exit "$rc"
    package_arch "$arch"
    BUILT+=("$arch")
done

echo ""
echo "========================================="
echo "Linux packages complete"
echo "========================================="
echo "Built:   ${BUILT[*]:-none}"
echo "Skipped: ${SKIPPED[*]:-none}"
ls -la "$OUT"/Install_FM-1Ception_*_Linux_*.zip 2>/dev/null || true
echo ""