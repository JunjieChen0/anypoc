## Important Constraints

- **NO standalone C/C++ programs using Hermes embedding APIs**: NEVER create standalone harnesses that call Hermes/JSI APIs (for example `facebook::hermes::makeHermesRuntime()`, `facebook::hermes::makeHermesRuntimeNoThrow()`, or `jsi::Runtime::evaluateJavaScript()`) to trigger the bug.
- **NO React Native embedding-only trigger paths**: do not rely on custom host apps or React Native integration code to reach the bug.
- All bugs must be reproducible by invoking the Hermes CLI binary directly: `/opt/hermes/build_asan/bin/hermes`.
- The PoC must trigger the real bug through normal Hermes CLI inputs (JavaScript source or Hermes bytecode files), not through internal-only runtime wiring.
- If a bug cannot be triggered through the Hermes CLI binary, it is out of scope.

## Build Instructions

The Hermes binary is pre-built with AddressSanitizer enabled.

To rebuild after making changes:
```bash
cmake -S /opt/hermes -B /opt/hermes/build_asan -G Ninja \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=Debug \
  -DHERMES_ENABLE_ADDRESS_SANITIZER=ON && \
cmake --build /opt/hermes/build_asan -j"$(nproc)" --target hermes
```

To do a clean rebuild:
```bash
rm -rf /opt/hermes/build_asan && \
cmake -S /opt/hermes -B /opt/hermes/build_asan -G Ninja \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=Debug \
  -DHERMES_ENABLE_ADDRESS_SANITIZER=ON && \
cmake --build /opt/hermes/build_asan -j"$(nproc)" --target hermes
```

## Running Instructions

Run JavaScript source directly:
```bash
/opt/hermes/build_asan/bin/hermes /tmp/poc.js
```

Compile source to Hermes bytecode (`.hbc`):
```bash
/opt/hermes/build_asan/bin/hermes -emit-binary -out /tmp/poc.hbc /tmp/poc.js
```

Run Hermes bytecode:
```bash
/opt/hermes/build_asan/bin/hermes /tmp/poc.hbc
```

Pass script arguments through CLI:
```bash
/opt/hermes/build_asan/bin/hermes /tmp/poc.js -- arg1 arg2
```

Run in strict mode:
```bash
/opt/hermes/build_asan/bin/hermes -strict /tmp/poc.js
```

## Notes

- The build has AddressSanitizer (ASan) enabled for memory error detection.
- Focus on dangerous, user-reachable engine surfaces: parser/frontend handling of crafted JS, bytecode generation and loading paths (`-emit-binary` and `.hbc` execution), runtime object/array/string operations, and GC interactions.
- Keep PoCs small and deterministic, and prefer direct CLI-triggerable crashes or sanitizer findings.
- Set `ASAN_OPTIONS` to improve signal quality:
  ```bash
  export ASAN_OPTIONS="detect_leaks=1:abort_on_error=1:symbolize=1:strict_string_checks=1:check_initialization_order=1"
  ```
