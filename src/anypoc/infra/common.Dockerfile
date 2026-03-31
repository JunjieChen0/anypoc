# Common build/debug toolchain image, layered on top of anypoc-base.
# Provides the heavy C/C++/Rust toolchains and debugging utilities that most
# project images need. Project Dockerfiles should `FROM zzjas/anypoc-common:latest`.

ARG BASE_IMAGE=zzjas/anypoc-base:latest
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

# Heavier dev/build/debug toolchain shared across most project images.
RUN apt-get update && apt-get install -y \
    file \
    lsof \
    htop \
    tree \
    netcat-openbsd \
    net-tools \
    libssl-dev \
    pkg-config \
    gperf \
    cmake \
    ninja-build \
    autoconf \
    automake \
    libtool \
    clang \
    clang-format \
    clang-tidy \
    gdb \
    lldb \
    strace \
    ltrace \
    linux-tools-generic \
    binutils \
    valgrind \
    llvm \
    llvm-dev \
    lld \
    inotify-tools \
    && rm -rf /var/lib/apt/lists/*

ENV ASAN_SYMBOLIZER_PATH=/usr/bin/llvm-symbolizer
ENV ASAN_OPTIONS="detect_leaks=0:symbolize=1:print_stacktrace=1:abort_on_error=1"
ENV RUST_BACKTRACE=1

# Install an immutable Rust toolchain under /opt and expose the real toolchain
# binaries via /usr/local/bin so project images can still run cargo as playground.
RUN export CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --default-toolchain stable --profile minimal --no-modify-path && \
    /opt/cargo/bin/rustup default stable && \
    /opt/cargo/bin/rustup show active-toolchain && \
    toolchain_bin="$(dirname "$(/opt/cargo/bin/rustup which cargo)")" && \
    for bin in "$toolchain_bin"/*; do \
        ln -sf "$bin" "/usr/local/bin/$(basename "$bin")"; \
    done && \
    printf '%s\n' \
        '#!/bin/sh' \
        'export RUSTUP_HOME=/opt/rustup' \
        'export CARGO_HOME=/opt/cargo' \
        'exec /opt/cargo/bin/rustup "$@"' \
        > /usr/local/bin/rustup && \
    chmod 755 /usr/local/bin/rustup && \
    chmod -R a+rX /opt/cargo /opt/rustup

ENV RUSTUP_HOME=/opt/rustup
