# memcached project image
# Extends the shared anypoc base image with memcached source and build

FROM zzjas/anypoc-common:latest

# Install memcached build dependencies
USER root
RUN apt-get update && apt-get install -y libevent-dev autotools-dev automake perl && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/memcached && chown -R playground:playground /opt/memcached

USER playground
WORKDIR /opt/memcached

# Clone memcached source code
RUN git clone https://github.com/memcached/memcached.git .

# Build memcached with AddressSanitizer enabled
RUN ./autogen.sh && \
    ./configure CC=clang CFLAGS="-g -O1 -fsanitize=address -fno-omit-frame-pointer" LDFLAGS="-fsanitize=address" && \
    make -j "$(nproc)"

# Verify build
RUN test -f /opt/memcached/memcached && \
    echo "Build verification: memcached binary exists" || \
    (echo "Build verification failed: memcached binary not found" && exit 1)

WORKDIR /opt/memcached
CMD ["/bin/bash"]
