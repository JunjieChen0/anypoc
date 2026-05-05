#!/usr/bin/env bash
# run_poc.sh — compile a C file statically and run it as PID 1 inside the
# kernel built into this image, under qemu.
#
# Usage: run_poc.sh <poc.c> [timeout_seconds]

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $0 <poc.c> [timeout_seconds]" >&2
    exit 2
fi

POC_SRC="$1"
TIMEOUT="${2:-60}"

if [ ! -f "$POC_SRC" ]; then
    echo "error: $POC_SRC not found" >&2
    exit 2
fi

KERNEL=/opt/linux/kernel/arch/x86/boot/bzImage
BASE_INITRAMFS=/opt/linux/initramfs.cpio.gz
SKEL=/opt/linux/initramfs

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Static build so we have no libc dependencies inside the busybox initramfs.
gcc -static -O0 -g -o "$WORK/run" "$POC_SRC"

# Repack the initramfs with the compiled binary slotted in at /poc/run.
STAGE="$WORK/rootfs"
mkdir -p "$STAGE"
( cd "$STAGE" && zcat "$BASE_INITRAMFS" | cpio -idm --quiet )
install -m 0755 "$WORK/run" "$STAGE/poc/run"
( cd "$STAGE" && find . -print0 | cpio --null -o --format=newc --quiet | gzip -9 > "$WORK/initramfs.cpio.gz" )

# Prefer KVM, fall back to TCG. KVM needs /dev/kvm passed into the container.
ACCEL="tcg"
if [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi
echo "[run_poc] accel=$ACCEL timeout=${TIMEOUT}s"

set +e
timeout --foreground -k 5 "$TIMEOUT" qemu-system-x86_64 \
    -accel "$ACCEL" \
    -m 2G \
    -smp 2 \
    -kernel "$KERNEL" \
    -initrd "$WORK/initramfs.cpio.gz" \
    -append "console=ttyS0 panic=1 oops=panic nokaslr quiet" \
    -nographic \
    -no-reboot
rc=$?
set -e

# timeout(1) returns 124 when it had to kill qemu; surface that as a
# distinguishable exit code so the caller knows the kernel never halted.
if [ "$rc" -eq 124 ]; then
    echo "[run_poc] qemu timed out after ${TIMEOUT}s" >&2
fi
exit "$rc"
