# sqlite project image
# Extends the shared anypoc base image with sqlite source and build

FROM zzjas/anypoc-common:latest

USER root

# Install dependencies for building SQLite
RUN apt-get update && apt-get install -y \
    tcl \
    tcl-dev \
    libreadline-dev \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/sqlite && chown -R playground:playground /opt/sqlite

USER playground
WORKDIR /opt/sqlite

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Clone SQLite source from GitHub mirror (easier than fossil)
RUN git clone https://github.com/sqlite/sqlite.git .

# Build SQLite with Address Sanitizer
# Using the configure script with ASan flags
RUN ./configure \
    CC="clang" \
    CFLAGS="-g -O1 -fsanitize=address -fno-omit-frame-pointer" \
    LDFLAGS="-fsanitize=address" \
    --disable-tcl \
    --enable-debug \
    && make -j$(nproc)

# Build the sqlite3 shell with ASan
RUN clang -g -O1 -fsanitize=address -fno-omit-frame-pointer \
    -DSQLITE_DEBUG \
    -DSQLITE_ENABLE_API_ARMOR \
    shell.c sqlite3.c \
    -lpthread -ldl -lm \
    -o sqlite

# Verify build
RUN test -f /opt/sqlite/sqlite && \
    echo "Build verification: SQLite ASan binary exists" || \
    (echo "Build verification failed: SQLite binary not found" && exit 1)

CMD ["/bin/bash"]
