## Build Instructions

### Rebuild with ASan (already done in Docker image)
```bash
cd /opt/sqlite

# Clean previous build
make clean

# Configure with ASan
./configure \
    CC="clang" \
    CFLAGS="-g -O1 -fsanitize=address -fno-omit-frame-pointer" \
    LDFLAGS="-fsanitize=address" \
    --disable-tcl \
    --enable-debug

# Build
make -j$(nproc)

# Build standalone sqlite3 shell with ASan
clang -g -O1 -fsanitize=address -fno-omit-frame-pointer \
    -DSQLITE_DEBUG \
    -DSQLITE_ENABLE_API_ARMOR \
    shell.c sqlite3.c \
    -lpthread -ldl -lm \
    -o sqlite
```

### Build without sanitizers (for comparison)
```bash
cd /opt/sqlite
make clean
./configure
make -j$(nproc)
```

## Running Instructions

### Interactive shell
```bash
/opt/sqlite/sqlite [database_file]
```

### Execute SQL from file
```bash
/opt/sqlite/sqlite database.db < script.sql
```

### Execute SQL from command line
```bash
/opt/sqlite/sqlite database.db "SELECT * FROM table;"
```

### Run with in-memory database
```bash
/opt/sqlite/sqlite :memory:
```

## Notes

- The ASan build uses `-O1` optimization for better performance while maintaining good error detection
- `SQLITE_DEBUG` enables additional runtime checks
- `SQLITE_ENABLE_API_ARMOR` adds extra parameter validation
- When ASan detects an issue, it will print a detailed stack trace
- Set `ASAN_OPTIONS` environment variable to customize ASan behavior:
  ```bash
  export ASAN_OPTIONS="detect_leaks=1:abort_on_error=1:symbolize=1"
  ```
