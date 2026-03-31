# hermes project image
# Extends the shared anypoc base image with Hermes source and build

FROM zzjas/anypoc-common:latest

USER root

# Install Hermes build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    git \
    ninja-build \
    libicu-dev \
    libreadline-dev \
    python3 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/hermes && chown -R playground:playground /opt/hermes

USER playground
WORKDIR /opt/hermes

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Download Hermes source code directly into the project root
RUN echo "CACHE_BUST=${CACHE_BUST}" && \
    git clone https://github.com/facebook/hermes.git .

# Build Hermes CLI with AddressSanitizer enabled
RUN cmake -S /opt/hermes -B /opt/hermes/build_asan -G Ninja \
    -DCMAKE_C_COMPILER=clang \
    -DCMAKE_CXX_COMPILER=clang++ \
    -DCMAKE_BUILD_TYPE=Debug \
    -DHERMES_ENABLE_ADDRESS_SANITIZER=ON && \
    cmake --build /opt/hermes/build_asan -j"$(nproc)" --target hermes

# Simple build verification test
RUN test -f /opt/hermes/build_asan/bin/hermes && \
    echo "Build verification: Hermes ASan binary exists" || \
    (echo "Build verification failed: Hermes binary not found" && exit 1)

WORKDIR /opt/hermes
CMD ["/bin/bash"]
