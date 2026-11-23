#!/bin/bash
# Build every FM-1Ception installer from the Mac — Xfer Records
#
# macOS is built natively; Windows and Linux are built inside the Parallels VMs through
# `prlctl exec`, reading this checkout (and the Libraries/Juce beside it) over the shared
# "Home" folder. Everything lands in <repo>/Installers; per-platform logs go to build-logs.
#
# Usage:
#   installer/build_all.sh [mac] [windows] [linux] [--no-notarize] [--skip-build]
#     no platform argument = mac and windows (linux is opt-in).
#     --skip-build repackages the existing Release builds (signing, notarization, installers only).
#
# Environment overrides:
#   FM1C_WIN_VM      Parallels VM name (auto-detected: "Windows*")
#   FM1C_LINUX_VM     Parallels VM name (auto-detected: "Ubuntu*")
#   FM1C_WIN_REPO    repo path as seen from inside the Windows VM
#   FM1C_LINUX_REPO  repo path as seen from inside the Linux VM (default /media/psf/Home/...)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/build-logs"
OUT="$ROOT/Installers"
mkdir -p "$LOGS" "$OUT"

DO_MAC=0; DO_WIN=0; DO_LINUX=0; MAC_ARGS=(); WIN_ARGS=""; LINUX_ARGS=(--arch arm64)
for arg in "$@"; do
    case "$arg" in
        mac|macos)     DO_MAC=1 ;;
        win|windows)   DO_WIN=1 ;;
        linux)         DO_LINUX=1 ;;
        --no-notarize) MAC_ARGS+=("--no-notarize") ;;
        --skip-build)  MAC_ARGS+=("--skip-build"); WIN_ARGS=" --skip-build"; LINUX_ARGS+=(--skip-build) ;;
        *) echo "Unknown option: $arg"; echo "Usage: $0 [mac] [windows] [linux] [--no-notarize] [--skip-build]"; exit 1 ;;
    esac
done
if [ $((DO_MAC + DO_WIN + DO_LINUX)) -eq 0 ]; then DO_MAC=1; DO_WIN=1; fi

# The shared "Home" folder exposes $HOME as \\Mac\Home (Windows) and /media/psf/Home (Linux).
case "$ROOT" in
    "$HOME"/*) REL="${ROOT#"$HOME"/}" ;;
    *) REL="" ;;
esac
WIN_REPO="${FM1C_WIN_REPO:-}"
LINUX_REPO="${FM1C_LINUX_REPO:-}"
if [ -n "$REL" ]; then
    [ -n "$WIN_REPO" ]   || WIN_REPO='\\Mac\Home\'"${REL//\//\\}"
    [ -n "$LINUX_REPO" ] || LINUX_REPO="/media/psf/Home/$REL"
fi

find_vm() { prlctl list -a -o name 2>/dev/null | tail -n +2 | grep -i -m1 "$1" || true; }
ensure_running() {
    local vm="$1" status
    status="$(prlctl list -a -o status,name 2>/dev/null | grep -F " $vm" | awk '{print $1}')"
    if [ "$status" != "running" ]; then
        echo "Starting VM \"$vm\"..."
        prlctl start "$vm" || return 1
        local ready=0
        for _ in $(seq 1 30); do
            prlctl exec "$vm" echo ok >/dev/null 2>&1 && { ready=1; break; }
            sleep 5
        done
        [ "$ready" = 1 ] || { echo "ERROR: VM \"$vm\" did not become ready"; return 1; }
    fi
}

run_mac() {
    echo "[mac] building..."
    bash "$ROOT/installer/macos/make_installer.sh" "${MAC_ARGS[@]+"${MAC_ARGS[@]}"}" > "$LOGS/macos.log" 2>&1
}

run_windows() {
    local vm="${FM1C_WIN_VM:-$(find_vm windows)}"
    [ -n "$vm" ] || { echo "[windows] ERROR: no Windows VM found (set FM1C_WIN_VM)"; return 1; }
    [ -n "$WIN_REPO" ] || { echo "[windows] ERROR: repo is outside \$HOME; set FM1C_WIN_REPO"; return 1; }
    ensure_running "$vm" || return 1
    echo "[windows] building in \"$vm\" from $WIN_REPO ..."
    prlctl exec "$vm" --current-user cmd /c "${WIN_REPO}\\installer\\windows\\build_installer.bat${WIN_ARGS}" > "$LOGS/windows.log" 2>&1
}

run_linux() {
    local vm="${FM1C_LINUX_VM:-$(find_vm ubuntu)}"
    [ -n "$vm" ] || { echo "[linux] ERROR: no Ubuntu VM found (set FM1C_LINUX_VM)"; return 1; }
    [ -n "$LINUX_REPO" ] || { echo "[linux] ERROR: repo is outside \$HOME; set FM1C_LINUX_REPO"; return 1; }
    ensure_running "$vm" || return 1
    echo "[linux] building in \"$vm\" from $LINUX_REPO ..."
    # --current-user: the login has Rust, cmake and ninja on PATH (root exec often does not).
    local linux_args=""
    [ "${#LINUX_ARGS[@]}" -gt 0 ] && linux_args="${LINUX_ARGS[*]}"
    prlctl exec "$vm" --current-user bash -lc \
        "export PATH=\"\$HOME/.cargo/bin:\$PATH\"; bash \"${LINUX_REPO}/installer/linux/build_packages.sh\" ${linux_args}" \
        > "$LOGS/linux.log" 2>&1
}

START=$(date +%s)
RESULT_mac=""; RESULT_windows=""; RESULT_linux=""
WIN_PID=""; LINUX_PID=""
if [ "$DO_WIN" = 1 ];   then run_windows & WIN_PID=$!; fi
if [ "$DO_LINUX" = 1 ]; then run_linux   & LINUX_PID=$!; fi
if [ "$DO_MAC" = 1 ];   then run_mac; RESULT_mac=$?; fi
if [ -n "$WIN_PID" ];     then wait "$WIN_PID";     RESULT_windows=$?; fi
if [ -n "$LINUX_PID" ];   then wait "$LINUX_PID";   RESULT_linux=$?; fi

echo ""
echo "========================================="
echo "Installer summary  ($(( ($(date +%s) - START) / 60 )) min)"
echo "========================================="
FAILED=0
for p in mac windows linux; do
    eval "rc=\$RESULT_$p"
    [ -n "$rc" ] || continue
    log="$p.log"; [ "$p" = mac ] && log="macos.log"
    if [ "$rc" = 0 ]; then
        echo "  $p: OK        (log: build-logs/$log)"
    else
        echo "  $p: FAILED    (log: build-logs/$log)"; FAILED=1
    fi
done
if [ -n "$RESULT_mac" ] && grep -q "Notarized:  no" "$LOGS/macos.log" 2>/dev/null; then
    echo "  mac: package is signed but NOT notarized — see build-logs/macos.log"
fi
echo ""
ls -la "$OUT" | grep -E '\.(pkg|exe|zip)$' || echo "  (no installers found in $OUT)"
echo ""
exit $FAILED