# ffmpeg project image
# Extends the shared anypoc base image with FFmpeg source and build

FROM zzjas/anypoc-common:latest

USER root
RUN mkdir -p /opt/ffmpeg && chown -R playground:playground /opt/ffmpeg

USER playground
WORKDIR /opt/ffmpeg

# Clone FFmpeg source code
RUN git clone https://github.com/FFmpeg/FFmpeg.git .

# Configure and build FFmpeg with AddressSanitizer enabled
# --enable-nonfree and --enable-gpl for broader codec coverage
# --disable-stripping to preserve debug symbols
RUN ./configure \
        --cc=clang \
        --cxx=clang++ \
        --extra-cflags="-g -O1 -fsanitize=address -fno-omit-frame-pointer" \
        --extra-ldflags="-fsanitize=address" \
        --enable-gpl \
        --disable-stripping \
        --disable-optimizations \
        --disable-x86asm && \
    make -j "$(nproc)"

# Verify build
RUN test -f /opt/ffmpeg/ffmpeg && \
    echo "Build verification: ffmpeg binary exists" || \
    (echo "Build verification failed: ffmpeg binary not found" && exit 1)

WORKDIR /opt/ffmpeg
CMD ["/bin/bash"]
