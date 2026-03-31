# freetype project image
# Extends the shared anypoc base image with FreeType source and build

FROM zzjas/anypoc-common:latest

USER root
RUN mkdir -p /opt/freetype && chown -R playground:playground /opt/freetype

USER playground
WORKDIR /opt/freetype

# Clone FreeType source code
RUN git clone https://github.com/freetype/freetype.git .

# Build FreeType as a static library with AddressSanitizer enabled using CMake
RUN cmake -B build \
        -DCMAKE_C_COMPILER=clang \
        -DCMAKE_C_FLAGS="-g -O1 -fsanitize=address -fno-omit-frame-pointer" \
        -DBUILD_SHARED_LIBS=OFF && \
        cmake --build build -j "$(nproc)"

# Verify build
RUN test -f /opt/freetype/build/libfreetype.a && \
    echo "Build verification: libfreetype.a exists" || \
    (echo "Build verification failed: libfreetype.a not found" && exit 1)

WORKDIR /opt/freetype
CMD ["/bin/bash"]
