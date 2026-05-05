## Important Constraints

- The PoC must be a single C source file that runs as PID 1 inside a freshly-booted Linux kernel under qemu. It triggers the bug via syscalls / `/proc` / `/sys` / `/dev` from userspace.
- **NO custom kernel modules** loaded at runtime — the bug must be reachable from an unmodified built kernel via standard userspace interfaces.
- **NO patching the kernel** to make the bug reachable. If a bug is only reachable with code changes, it is out of scope.
- The PoC binary is statically linked. You may use plain libc (`syscall(2)`, `open`, `ioctl`, `mmap`, etc.) and inline assembly, but no shared libraries beyond what `gcc -static` produces.
- The kernel is built with KASAN (generic, inline) and UBSAN. A successful PoC is one where the serial console shows a `BUG:` / `KASAN:` / `UBSAN:` report (or similar oops/panic) attributable to the targeted code path.
- The kernel boots with `panic=1 oops=panic`, so any oops halts the VM. That is the success signal.

## Build & Run

The kernel and base initramfs are pre-built into the image. To build and run a PoC:

```bash
/opt/linux/run_poc.sh /path/to/poc.c            # default 60s timeout
/opt/linux/run_poc.sh /path/to/poc.c 120        # custom timeout in seconds
```

The script:
1. Static-compiles `poc.c` with `gcc -static -O0 -g`.
2. Repacks the busybox initramfs with the compiled binary at `/poc/run`.
3. Boots `qemu-system-x86_64` with the prebuilt `bzImage` and the new initramfs, accel=kvm if `/dev/kvm` is writable, otherwise tcg.
4. Returns qemu's exit code (124 if the timeout fired before the kernel halted).

## Rebuilding the kernel

The kernel source lives at `/opt/linux/kernel`. To rebuild after editing config or sources:

```bash
cd /opt/linux/kernel && make -j"$(nproc)"
```

The `bzImage` is produced at `/opt/linux/kernel/arch/x86/boot/bzImage` and is what `run_poc.sh` boots — no further packaging step is needed.

## Notes

- Console is ttyS0; `printf` from the PoC and kernel messages both end up on stdout under `-nographic`.
- The initramfs is busybox-only — no package manager, no network tools beyond what busybox provides.
- KASLR is disabled (`nokaslr` + `CONFIG_RANDOMIZE_BASE=n`) so addresses in KASAN reports stay stable across runs.
- After the PoC binary exits, init calls `poweroff -f`, so a clean exit produces a clean qemu shutdown rather than a timeout.
