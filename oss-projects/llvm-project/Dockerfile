# llvm-project project image
# Extends the shared anypoc base image with LLVM/Clang source and build

FROM zzjas/anypoc-common:latest

USER root

# Install dependencies for building LLVM
RUN apt-get update && apt-get install -y \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    zlib1g-dev \
    libncurses-dev \
    libxml2-dev \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/llvm-project && chown -R playground:playground /opt/llvm-project

USER playground
WORKDIR /opt/llvm-project

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Clone LLVM source directly into the project root
RUN git clone https://github.com/llvm/llvm-project.git .

WORKDIR /opt/llvm-project/build

# Configure LLVM with CMake (Release build, only clang and lld)
RUN cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLVM_ENABLE_PROJECTS="clang;lld" \
    -DLLVM_TARGETS_TO_BUILD="X86" \
    -DLLVM_ENABLE_ASSERTIONS=ON \
    /opt/llvm-project/llvm

# Build LLVM/Clang
RUN ninja -j$(nproc)

# Verify build
RUN test -f /opt/llvm-project/build/bin/clang && \
    echo "Build verification: Clang binary exists" || \
    (echo "Build verification failed: Clang binary not found" && exit 1)

CMD ["/bin/bash"]
