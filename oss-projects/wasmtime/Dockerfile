# wasmtime project image
# Extends the shared anypoc base image with Wasmtime source and build

FROM zzjas/anypoc-common:latest

USER root
WORKDIR /opt/wasmtime

# Clone wasmtime source code directly into the project root
RUN git clone https://github.com/bytecodealliance/wasmtime.git . \
 && git submodule update --init --recursive

RUN rustup default stable

# Build wasmtime
RUN cargo build

# Verify binary was built
RUN test -x /opt/wasmtime/target/debug/wasmtime

USER playground
WORKDIR /opt/wasmtime
CMD ["/bin/bash"]
