## Build Instructions

```bash
# Normal build
cargo build

# Release build
cargo build --release
```

## Running Instructions

```bash
# Debug build
./target/debug/wasmtime

# Release build
./target/release/wasmtime
```

## Notes

You should not try to use Wasmtime APIs in invalid ways.

You should NEVER try to create standalone "replication" to demonstrate the buggy behavior.
All PoCs must show the bug is triggerable from valid use of Wasmtime.
