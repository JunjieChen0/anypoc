# openssl project image
# Extends the shared anypoc base image with OpenSSL source and build

FROM zzjas/anypoc-common:latest

USER root
RUN mkdir -p /opt/openssl && chown -R playground:playground /opt/openssl

USER playground
WORKDIR /opt/openssl

# Clone OpenSSL source code
RUN git clone https://github.com/openssl/openssl.git .

# Configure and build OpenSSL with AddressSanitizer enabled
RUN ./Configure enable-asan -g -O1 -fno-omit-frame-pointer && \
    make -j "$(nproc)"

# Verify build
RUN test -f /opt/openssl/apps/openssl && \
    echo "Build verification: openssl binary exists" || \
    (echo "Build verification failed: openssl binary not found" && exit 1)

WORKDIR /opt/openssl
CMD ["/bin/bash"]
