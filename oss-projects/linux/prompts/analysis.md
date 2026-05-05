# Reject Bugs

If the bug report satisfies any of the following conditions, reject it without further exploration:

1. Requires loading a custom out-of-tree kernel module
2. Requires patching the kernel source to be reachable
3. Only reproduces under a hardware-specific driver that cannot be exercised from a generic qemu-system-x86_64 VM (e.g. needs real GPU, real NIC, vendor-specific firmware)
4. Requires root on the host (we already run as root inside the VM as PID 1, but the bug must not require host-side privileges to set up)
5. Requires a non-x86_64 architecture
6. Requires a specific kernel config flag that conflicts with KASAN or with the prebuilt image
7. Race-condition bugs whose only reproducer requires real SMP timing on bare metal — flaky reproducers under qemu+KVM with `-smp 2` are acceptable, but bugs that fundamentally cannot be triggered in a 2-vCPU VM are out of scope
