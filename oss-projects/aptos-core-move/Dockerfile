# aptos-core-move project image
# Extends the shared anypoc base image with aptos-core source and a debug build of the aptos CLI
# Focus: Move compiler and runtime (third_party/move)

FROM zzjas/anypoc-common:latest

# Install aptos build dependencies not in the shared base image
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libudev-dev libdw-dev lld \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/dotnet
WORKDIR /opt/aptos-core-move

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Clone aptos-core directly into the project root
RUN git clone https://github.com/aptos-labs/aptos-core.git .

# Create a sidecar bin/ for prover tools (Z3, CVC5, etc.) installed below.
# Lives inside the source tree but is git-ignored — fine for an opaque image.
RUN mkdir -p /opt/aptos-core-move/bin

# Build the aptos CLI binary in debug mode
# rust-toolchain.toml in the repo will install the required toolchain (1.93.1) automatically
RUN cargo build -p aptos

# Verify build
RUN test -f /opt/aptos-core-move/target/debug/aptos && \
    echo "Build verification: aptos binary exists" || \
    (echo "Build verification failed: aptos binary not found" && exit 1)

# Install Move Prover dependencies (Z3, .NET, Boogie, CVC5)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    gettext zlib1g wget unzip curl \
    && rm -rf /var/lib/apt/lists/*

# Versions from aptos-core/scripts/dev_setup.sh
ENV Z3_VERSION=4.11.2
ENV CVC5_VERSION=0.0.3
ENV DOTNET_VERSION=8.0
ENV BOOGIE_VERSION=3.5.1
ENV DOTNET_ROOT=/opt/dotnet
ENV PATH="${DOTNET_ROOT}/tools:${DOTNET_ROOT}:/opt/aptos-core-move/bin:${PATH}"
ENV Z3_EXE=/opt/aptos-core-move/bin/z3
ENV CVC5_EXE=/opt/aptos-core-move/bin/cvc5
ENV BOOGIE_EXE=/opt/dotnet/tools/boogie
# Increase thread stack size to prevent stack overflow in the Move Prover
ENV RUST_MIN_STACK=8388608

# Install Z3
RUN cd /tmp && \
    curl -LOs "https://github.com/Z3Prover/z3/releases/download/z3-${Z3_VERSION}/z3-${Z3_VERSION}-x64-glibc-2.31.zip" && \
    unzip -q "z3-${Z3_VERSION}-x64-glibc-2.31.zip" && \
    cp "z3-${Z3_VERSION}-x64-glibc-2.31/bin/z3" /opt/aptos-core-move/bin/z3 && \
    chmod +x /opt/aptos-core-move/bin/z3 && \
    rm -rf /tmp/z3-*

# Install CVC5
RUN cd /tmp && \
    curl -LOs "https://github.com/cvc5/cvc5/releases/download/cvc5-${CVC5_VERSION}/cvc5-Linux" && \
    cp cvc5-Linux /opt/aptos-core-move/bin/cvc5 && \
    chmod +x /opt/aptos-core-move/bin/cvc5 && \
    rm -f /tmp/cvc5-Linux

# Install .NET SDK and Boogie
RUN wget --tries 10 --retry-connrefused --waitretry=5 \
      https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh && \
    chmod +x /tmp/dotnet-install.sh && \
    TERM=xterm /tmp/dotnet-install.sh --channel ${DOTNET_VERSION} --install-dir "${DOTNET_ROOT}" --version latest && \
    rm /tmp/dotnet-install.sh && \
    mkdir -p "${DOTNET_ROOT}/tools" && \
    "${DOTNET_ROOT}/dotnet" tool update --tool-path "${DOTNET_ROOT}/tools/" Boogie --version ${BOOGIE_VERSION}

# Verify prover dependencies
RUN z3 --version && cvc5 --version && boogie /version

USER playground
WORKDIR /opt/aptos-core-move
CMD ["/bin/bash"]
