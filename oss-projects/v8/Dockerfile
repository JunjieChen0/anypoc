# v8 project image
# Extends the shared anypoc base image with V8 source and build

FROM zzjas/anypoc-common:latest

# V8-specific environment variables
ENV V8_USE_EXTERNAL_STARTUP_DATA=0

USER root
RUN mkdir -p /opt/v8/tools && chown -R playground:playground /opt/v8

USER playground
WORKDIR /opt/v8

# Install depot_tools (official Google Chromium/V8 tooling)
RUN git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/v8/tools/depot_tools
ENV PATH="/opt/v8/tools/depot_tools:${PATH}"

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Download V8 source code using official tooling (full clone/history)
RUN fetch v8

# Build V8 d8 shell with ASan enabled
RUN cd /opt/v8/v8 && \
    tools/dev/v8gen.py x64.release -- is_asan=true is_lsan=true && \
    autoninja -C out.gn/x64.release d8

# Simple build verification test
RUN test -f /opt/v8/v8/out.gn/x64.release/d8 && \
    echo "Build verification: V8 d8 binary exists" || \
    (echo "Build verification failed: V8 d8 binary not found" && exit 1)

WORKDIR /opt/v8/v8
CMD ["/bin/bash"]
