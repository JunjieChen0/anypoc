# redis project image
# Extends the shared anypoc base image with Redis source and build

FROM zzjas/anypoc-common:latest

USER root
RUN mkdir -p /opt/redis && chown -R playground:playground /opt/redis

USER playground
WORKDIR /opt/redis

# Clone Redis source code (shallow clone for faster download)
RUN git clone https://github.com/redis/redis.git .

# Build Redis with AddressSanitizer enabled
# SANITIZER=address enables ASan in Redis build system
# DISABLE_WERRORS=yes prevents warnings from being treated as errors
RUN make -j "$(nproc)" SANITIZER=address DISABLE_WERRORS=yes

# Verify build
RUN test -f /opt/redis/src/redis-server && \
    echo "Build verification: Redis server binary exists" || \
    (echo "Build verification failed: Redis server binary not found" && exit 1)

WORKDIR /opt/redis
CMD ["/bin/bash"]
