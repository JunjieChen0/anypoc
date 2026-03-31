# quickjs project image
# Extends the shared anypoc base image with QuickJS source and build

FROM zzjas/anypoc-common:latest

USER root
RUN mkdir -p /opt/quickjs && chown -R playground:playground /opt/quickjs

USER playground
WORKDIR /opt/quickjs

# Clone QuickJS source code
RUN git clone https://github.com/quickjs-ng/quickjs.git .

# Build QuickJS with AddressSanitizer enabled
# QJS_ENABLE_ASAN=ON enables ASan via QuickJS's CMake build system
RUN cmake -B build \
        -DCMAKE_C_COMPILER=clang \
        -DCMAKE_BUILD_TYPE=Debug \
        -DQJS_ENABLE_ASAN=ON \
        -DQJS_BUILD_WERROR=OFF && \
        cmake --build build -j "$(nproc)"

# Verify build
RUN test -f /opt/quickjs/build/qjs && \
    echo "Build verification: qjs binary exists" || \
    (echo "Build verification failed: qjs binary not found" && exit 1)

WORKDIR /opt/quickjs
CMD ["/bin/bash"]
