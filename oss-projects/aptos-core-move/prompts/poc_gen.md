## Important Constraints

- **NO standalone Rust programs calling Move VM APIs directly**: NEVER create a standalone Rust program that calls Move VM or compiler functions (e.g., `MoveVM::new()`, `Session::execute_function()`, `Compiler::new()`, `move_compile()`, etc.) to trigger the bug.
- **Only `aptos move` subcommands are in scope**: All bugs must be triggered via the `aptos move` subcommands (`compile`, `test`, `run-script`, `disassemble`, `decompile`, etc.).
- **No blockchain/node subcommands**: Do not use `aptos node`, `aptos validator`, or any network-dependent subcommands. The bug must be reproducible entirely offline.
- **No on-chain publishing**: Do not attempt to publish packages to a live network. Use local compilation and simulation only.
- If a bug cannot be triggered via an `aptos move` subcommand using crafted Move source or bytecode, it is out of scope.

## Build Instructions

The `aptos` binary is pre-built in debug mode (with full debug symbols).

To rebuild after making changes:
```bash
cd /opt/aptos-core-move && cargo build -p aptos
```

To do a clean rebuild:
```bash
cd /opt/aptos-core-move && cargo clean -p aptos && cargo build -p aptos
```

## Running Instructions

All commands use the binary at `/opt/aptos-core-move/target/debug/aptos`.

### Setting up a minimal Move package

Most `aptos move` commands operate on a Move package. Create a minimal one:
```bash
mkdir -p /tmp/mypkg/sources
cat > /tmp/mypkg/Move.toml << 'EOF'
[package]
name = "mypkg"
version = "1.0.0"
[addresses]
mypkg = "0x1"
EOF
cat > /tmp/mypkg/sources/main.move << 'EOF'
module mypkg::main {
    public fun hello(): u64 { 42 }
}
EOF
```

### Compile a Move package
```bash
/opt/aptos-core-move/target/debug/aptos move compile --package-dir /tmp/mypkg
```

### Run Move unit tests
```bash
/opt/aptos-core-move/target/debug/aptos move test --package-dir /tmp/mypkg
```

### Compile and run a Move script
```bash
cat > /tmp/myscript.move << 'EOF'
script {
    fun main() {
        let _x: u64 = 1 + 1;
    }
}
EOF
/opt/aptos-core-move/target/debug/aptos move compile-script --script-path /tmp/myscript.move
/opt/aptos-core-move/target/debug/aptos move run-script --compiled-script-path /tmp/myscript.mv --local
```

### Disassemble Move bytecode
```bash
/opt/aptos-core-move/target/debug/aptos move disassemble --bytecode-path /path/to/module.mv
```

### Decompile Move bytecode
```bash
/opt/aptos-core-move/target/debug/aptos move decompile --bytecode-path /path/to/module.mv
```

### Compile with a specific compiler version
```bash
/opt/aptos-core-move/target/debug/aptos move compile --package-dir /tmp/mypkg --compiler-version 2
```

### Format Move source code
```bash
/opt/aptos-core-move/target/debug/aptos move fmt --package-dir /tmp/mypkg
```

## Notes

- This is a debug build — full debug symbols are available for stack traces
- Rust provides memory safety by default; bugs to look for include: panics (index out of bounds, unwrap on None/Err), integer overflows in debug mode, infinite loops, incorrect compilation output, and logic errors in the Move type checker or bytecode verifier
- The Move compiler and runtime live under `/opt/aptos-core-move/third_party/move/` — bugs in this subtree are in scope; bugs in aptos-specific wrappers outside this directory are lower priority
- Common attack surfaces:
  - Crafted Move source code → compiler (`third_party/move/move-compiler-v2/`)
  - Crafted Move bytecode → bytecode verifier (`third_party/move/move-bytecode-verifier/`)
  - Crafted Move bytecode → disassembler/decompiler (`third_party/move/tools/`)
  - Edge cases in Move type system, generics, and abilities
  - Integer arithmetic, borrow checker, and resource safety in the Move VM (`third_party/move/move-vm/`)
