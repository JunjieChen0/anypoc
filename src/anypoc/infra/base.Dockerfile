# Minimal base image with anypoc and just enough to run it.
# Heavier C/C++/Rust build & debug toolchains live in common.Dockerfile,
# which is layered on top of this image.

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH
ARG NODE_VERSION=20.11.0

# Minimal tooling needed to run anypoc itself: git for project clones,
# build-essential for any wheel native deps, python3 + venv for the anypoc
# venv at /opt/anypoc/.venv.
RUN apt-get update && apt-get install -y \
    ca-certificates \
    xz-utils \
    git \
    curl \
    wget \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    vim \
    coreutils \
    procps \
    psmisc \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install uv into /opt so runtime user remapping does not traverse toolchain files.
RUN mkdir -p /opt/uv && \
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/uv sh

# Install Node.js under /opt instead of the runtime home.
RUN case "${TARGETARCH:-amd64}" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    mkdir -p /opt/node && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" | \
        tar -xJ --strip-components=1 -C /opt/node

ENV PATH="/opt/uv:/opt/node/bin:/usr/local/bin:${PATH}"

# Install shared coding CLIs in the base image.
RUN npm install -g @openai/codex
RUN mkdir -p /opt/claude-home && \
    (HOME=/opt/claude-home bash -lc 'curl -fsSL https://claude.ai/install.sh | bash' && \
    if [ ! -x /usr/local/bin/claude ]; then \
        test -e /opt/claude-home/.local/bin/claude && \
        ln -sf /opt/claude-home/.local/bin/claude /usr/local/bin/claude; \
    fi) || echo "WARNING: Failed to install claude CLI (network issue), skipping"

# Pre-install anypoc's dependency closure so the cached venv is ready at
# container start. The project source itself is NOT copied into the image —
# it is bind-mounted read-only at `/opt/anypoc/src` at runtime, which lets
# users edit anypoc on the host and pick up changes without rebuilding.
#
# `--no-install-project` resolves and installs every dependency from uv.lock
# but skips installing the `anypoc` package itself. To make the bind-mounted
# source importable without writing to the venv at runtime, we drop a `.pth`
# file pointing at `/opt/anypoc/src` and hand-write entry-point shims for the
# CLI commands declared in pyproject.toml `[project.scripts]`.
WORKDIR /opt/anypoc
COPY pyproject.toml /opt/anypoc/pyproject.toml
COPY README.md /opt/anypoc/README.md
COPY .python-version /opt/anypoc/.python-version
COPY uv.lock /opt/anypoc/uv.lock
RUN uv sync --frozen --no-dev --no-install-project && \
    site_pkgs="$(/opt/anypoc/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')" && \
    echo "/opt/anypoc/src" > "${site_pkgs}/anypoc.pth" && \
    printf '%s\n' \
        '#!/opt/anypoc/.venv/bin/python' \
        'import sys' \
        'from anypoc.cli import main' \
        'sys.exit(main())' \
        > /opt/anypoc/.venv/bin/anypoc && \
    printf '%s\n' \
        '#!/opt/anypoc/.venv/bin/python' \
        'import sys' \
        'from anypoc.utils.permissions import main' \
        'sys.exit(main())' \
        > /opt/anypoc/.venv/bin/anypoc-perm && \
    chmod 755 /opt/anypoc/.venv/bin/anypoc /opt/anypoc/.venv/bin/anypoc-perm

# Create the container user with UID/GID matching the host user that ran the build.
# Defaults to 1000:1000 for portability; build.py injects the real host values via
# --build-arg PLAYGROUND_UID / PLAYGROUND_GID so files created in the image (e.g.,
# project source trees chowned to playground) are readable/writable by the same UID
# on the host without any runtime remapping.
ARG PLAYGROUND_UID=1000
ARG PLAYGROUND_GID=1000
RUN groupadd -o -g ${PLAYGROUND_GID} playground && \
    useradd -o -m -s /bin/bash -u ${PLAYGROUND_UID} -g ${PLAYGROUND_GID} playground && \
    echo "playground:playground" | chpasswd

# Make the installed toolchain readable to remapped runtime users.
RUN chmod -R a+rX /opt/anypoc /opt/uv /opt/node /opt/claude-home

# Seed writable runtime directories and the standard anypoc config root.
RUN mkdir -p /home/playground/.anypoc/projects /home/playground/.cache/anypoc /home/playground/.local/bin && \
    chown -R playground:playground /home/playground

COPY --chmod=755 src/anypoc/infra/entrypoint.sh /entrypoint.sh

ENV PATH="/opt/anypoc/.venv/bin:/opt/uv:/opt/node/bin:/usr/local/bin:${PATH}"

WORKDIR /home/playground
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash"]
