# linux project image
# Builds an upstream Linux kernel (master) with KASAN+UBSAN and a minimal
# busybox-based initramfs for booting under qemu. Includes a wrapper that
# compiles a single C file statically and runs it as PID 1 inside the VM.

FROM zzjas/anypoc-common:latest

USER root

# Kernel build deps + qemu + tools for crafting the initramfs.
RUN apt-get update && apt-get install -y \
    bc \
    bison \
    flex \
    libelf-dev \
    libssl-dev \
    libncurses-dev \
    dwarves \
    cpio \
    rsync \
    kmod \
    busybox-static \
    qemu-system-x86 \
    qemu-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/linux && chown -R playground:playground /opt/linux

USER playground
WORKDIR /opt/linux

# Cache bust to force kernel re-clone/rebuild without invalidating apt layers.
ARG CACHE_BUST=1

# Track upstream master. Shallow clone — we don't need history for builds.
RUN git clone --depth=1 https://github.com/torvalds/linux.git kernel

WORKDIR /opt/linux/kernel

# Base config: defconfig + KVM guest tuning (virtio drivers, serial console).
RUN make defconfig && make kvm_guest.config

# Sanitizers + debug info. KASAN_INLINE produces faster kernels than OUTLINE
# and is fine since we're not constrained on .text size.
#
# Plus: flip the highest-CVE-density "modules-by-default" subsystems to =y so
# they end up KASAN-instrumented and reachable from the initramfs (no module
# loader). See paths.md for the resulting attack surface map.
RUN ./scripts/config \
        -e CONFIG_DEBUG_INFO \
        -e CONFIG_DEBUG_INFO_DWARF4 \
        -e CONFIG_KASAN \
        -e CONFIG_KASAN_GENERIC \
        -e CONFIG_KASAN_INLINE \
        -e CONFIG_UBSAN \
        -e CONFIG_UBSAN_BOUNDS \
        -e CONFIG_UBSAN_SHIFT \
        -e CONFIG_UBSAN_DIV_ZERO \
        -e CONFIG_UBSAN_UNREACHABLE \
        -e CONFIG_PANIC_ON_OOPS \
        -d CONFIG_RANDOMIZE_BASE \
        -d CONFIG_DEBUG_INFO_REDUCED \
        -e CONFIG_USER_NS \
        -e CONFIG_NETFILTER \
        -e CONFIG_NETFILTER_ADVANCED \
        -e CONFIG_NETFILTER_XTABLES \
        -e CONFIG_NF_CONNTRACK \
        -e CONFIG_NF_TABLES \
        -e CONFIG_NF_TABLES_INET \
        -e CONFIG_NF_TABLES_IPV4 \
        -e CONFIG_NF_TABLES_IPV6 \
        -e CONFIG_NF_TABLES_NETDEV \
        -e CONFIG_NFT_CT \
        -e CONFIG_NFT_NAT \
        -e CONFIG_NFT_LIMIT \
        -e CONFIG_NFT_LOG \
        -e CONFIG_NFT_COUNTER \
        -e CONFIG_NFT_REJECT \
        -e CONFIG_NFT_COMPAT \
        -e CONFIG_NFT_HASH \
        -e CONFIG_NFT_FIB \
        -e CONFIG_NFT_FIB_INET \
        -e CONFIG_NFT_QUEUE \
        -e CONFIG_NFT_QUOTA \
        -e CONFIG_IP_NF_IPTABLES \
        -e CONFIG_IP_NF_FILTER \
        -e CONFIG_IP_NF_NAT \
        -e CONFIG_IP_NF_MANGLE \
        -e CONFIG_IP6_NF_IPTABLES \
        -e CONFIG_IP6_NF_FILTER \
        -e CONFIG_IP6_NF_NAT \
        -e CONFIG_IP6_NF_MANGLE \
        -e CONFIG_BT \
        -e CONFIG_BT_BREDR \
        -e CONFIG_BT_LE \
        -e CONFIG_BT_RFCOMM \
        -e CONFIG_BT_BNEP \
        -e CONFIG_BT_HIDP \
        -e CONFIG_BT_HCIVHCI \
        -e CONFIG_USB \
        -e CONFIG_USB_SUPPORT \
        -e CONFIG_USB_GADGET \
        -e CONFIG_USB_DUMMY_HCD \
        -e CONFIG_USB_RAW_GADGET \
        -e CONFIG_USB_HID \
        -e CONFIG_HID \
        -e CONFIG_HID_GENERIC \
        -e CONFIG_USB_STORAGE \
    && make olddefconfig

RUN make -j"$(nproc)"

RUN test -f /opt/linux/kernel/arch/x86/boot/bzImage \
    || (echo "Build verification failed: bzImage not found" && exit 1)

# Build a minimal busybox initramfs. Init script chains to /poc/run if it
# exists (run_poc.sh drops the compiled binary there at runtime), otherwise
# drops to a shell on the serial console.
WORKDIR /opt/linux/initramfs
RUN mkdir -p bin sbin etc proc sys dev usr/bin usr/sbin tmp poc \
    && cp "$(command -v busybox)" bin/busybox \
    && for applet in $(./bin/busybox --list); do \
           [ "$applet" = busybox ] && continue; \
           ln -sf busybox bin/"$applet"; \
       done \
    && printf '%s\n' \
        '#!/bin/busybox sh' \
        '/bin/busybox --install -s /bin' \
        'mount -t proc none /proc' \
        'mount -t sysfs none /sys' \
        'mount -t devtmpfs none /dev 2>/dev/null || mdev -s' \
        'echo "[init] kernel up, running poc"' \
        'if [ -x /poc/run ]; then' \
        '    /poc/run' \
        '    rc=$?' \
        '    echo "[init] poc exited rc=$rc"' \
        'else' \
        '    echo "[init] no /poc/run — dropping to shell"' \
        '    exec /bin/sh' \
        'fi' \
        'echo "[init] poweroff"' \
        'poweroff -f' \
        > init \
    && chmod +x init \
    && find . -print0 | cpio --null -ov --format=newc 2>/dev/null | gzip -9 > /opt/linux/initramfs.cpio.gz \
    && echo "Initramfs: $(du -h /opt/linux/initramfs.cpio.gz | cut -f1)"

# Wrapper script: takes a C file, statically compiles it, repacks the
# initramfs with the binary at /poc/run, and boots qemu.
COPY --chown=playground:playground oss-projects/linux/scripts/run_poc.sh /opt/linux/run_poc.sh
RUN chmod +x /opt/linux/run_poc.sh

# Sample PoC for smoke-testing the image: `/opt/linux/run_poc.sh /opt/linux/hello.c`
COPY --chown=playground:playground oss-projects/linux/scripts/hello.c /opt/linux/hello.c

# Final sanity check: boot the built kernel under qemu-TCG (no /dev/kvm
# during docker build) with hello.c as PID 1 and verify the expected
# strings reach the serial console. KASAN+UBSAN under TCG is slow, so
# allow up to 240s for boot+execute+poweroff.
RUN /opt/linux/run_poc.sh /opt/linux/hello.c 240 > /tmp/hello.log 2>&1; \
        rc=$?; \
        echo "===== hello.c qemu output ====="; cat /tmp/hello.log; echo "===== end ====="; \
        test "$rc" = "0" \
        && grep -q "hello world from PID 1" /tmp/hello.log \
        && grep -q "\[hello\] kernel: Linux" /tmp/hello.log \
        && echo "Sanity check: kernel boots and runs PoC binary" \
        && rm /tmp/hello.log

WORKDIR /opt/linux
CMD ["/bin/bash"]
