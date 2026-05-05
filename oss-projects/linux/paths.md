Path to source code: /opt/linux/kernel

Path to built kernel image: /opt/linux/kernel/arch/x86/boot/bzImage

Path to base initramfs: /opt/linux/initramfs.cpio.gz

Path to PoC runner: /opt/linux/run_poc.sh

Path to sample PoC: /opt/linux/hello.c


# Attack surface map

The kernel is built from upstream master with KASAN (generic, inline) +
UBSAN (bounds/shift/div_zero/unreachable). PoCs run as PID 1 (root, host
init namespace) inside a busybox initramfs under qemu — there is no module
loader and no `/lib/modules` in the rootfs, so **only built-in (`=y`) code
is reachable**. Everything below is built `=y` and is fair game; anything
not listed is either `=m` (compiled but unreachable) or `=n`.

## Reachable from a userspace PoC

### Core kernel
- Scheduler, mm (page allocator, slab/slub, vmalloc, GUP, mmap/mremap/mprotect, madvise), VFS, signals, futex, pipes, eventfd/signalfd/timerfd/epoll, **io_uring** (full ABI), IPC (msg/sem/shm), seccomp.
- Namespaces & cgroups: PID/NET/MNT/**USER**/UTS/IPC/CGROUP/TIME, all cgroup controllers. `CONFIG_USER_NS=y` so unprivileged-LPE PoCs that rely on user namespaces work.
- eBPF: full `bpf(2)` ABI, verifier, JIT, BTF.
- Tracing/perf: `perf_event_open(2)`, ftrace, kprobes, uprobes, tracepoints.

### Networking — bug-rich, all flipped to `=y`
- Socket layer + AF_UNIX, AF_INET / INET6, AF_PACKET, AF_NETLINK, raw sockets, TCP/UDP/ICMP.
- **Netfilter / nf_tables** — top CVE-density subsystem. Reachable via netlink (`NFNL_SUBSYS_NFTABLES`) and setsockopt iptables. Built-in: `nf_tables` core, `nf_conntrack`, inet/ipv4/ipv6/netdev families, expressions: ct, nat, limit, log, counter, reject, compat, hash, fib, queue, quota; legacy `iptables`/`ip6tables` with filter/nat/mangle.
- **Bluetooth** — AF_BLUETOOTH socket family, BR/EDR + LE stacks, RFCOMM, BNEP, HIDP. **`HCIVHCI`** built-in: a virtual HCI controller — open `/dev/vhci`, write HCI frames, exercise the whole HCI/L2CAP/SCO/RFCOMM parser tree. No real hardware required.

### USB — software-emulated host controller stack
- **`dummy_hcd` + `raw-gadget`**: write USB device descriptors from userspace and the kernel's own USB core / HID / storage parsers process them as if a real device was plugged in. Exercises `drivers/usb/core/`, `drivers/hid/`, `drivers/usb/storage/`.

### Filesystems
- ext4, proc, sysfs, devtmpfs, tmpfs, ramfs, configfs, debugfs, fusectl, overlayfs.

### Misc
- Block layer core; **virtio_blk, virtio_net, virtio_pci, virtio_console, 9p over virtio** (from `kvm_guest.config`).
- TTY/serial 8250, PCI core, ACPI core.
- Crypto: AF_ALG socket family + the small set of ciphers/hashes that defconfig builds in.
- Security frameworks: SELinux/AppArmor/Yama compiled in but inactive (no `security=…` on cmdline).

## Compiled but NOT reachable here (`=m` in defconfig, no module loader)

- Most device drivers: NICs (e1000/ixgbe/etc.), non-virtio block, NVMe, sound (ALSA), DRM/GPU, wireless / cfg80211 / mac80211, non-USB HID, USB HCDs other than `dummy_hcd`.
- Most filesystems beyond ext4 + the always-on pseudo-FSes: xfs, btrfs, f2fs, ntfs3, gfs2, ceph, nfs, cifs/smb, fat/exfat, isofs, udf, jffs2, ubifs, erofs, squashfs.
- Most non-mainstream network protocols: SCTP, DCCP, AX.25, IPVS, TIPC, RxRPC, KCM, vsock, L2TP.
- Crypto: most ciphers, hashes, AEAD constructs, KDFs.
- KVM host (`kvm.ko`, `kvm_intel.ko`, `kvm_amd.ko`).

## To pull more in

Edit the `./scripts/config -e …` block in the Dockerfile and rebuild. Flipping `=m → =y` keeps KASAN coverage. Common asks: `CONFIG_NTFS3_FS`, `CONFIG_F2FS_FS`, `CONFIG_BTRFS_FS`, `CONFIG_EROFS_FS` (filesystem-image-mount PoCs); `CONFIG_IP_SCTP`, `CONFIG_TIPC`, `CONFIG_VSOCKETS` (legacy net protocols).
