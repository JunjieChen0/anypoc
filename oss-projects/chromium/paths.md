Path to source code: /opt/chromium/src

Path to built binary: /opt/chromium/src/out/Asan/chrome

## You may modify the build config and rebuild

The pre-built binary is a convenient default, **not a constraint**. If a bug
only triggers under a different build configuration, you are free to edit the
GN args and rebuild. Examples of when to rebuild:

- The bug requires `is_debug = true` (DCHECKs, CHECK_*, debug-only codepaths,
  `DCHECK_IS_ON()` branches).
- The bug requires a different sanitizer (`is_ubsan = true`, `is_tsan = true`,
  `is_msan = true`, `is_lsan = true`) or combination.
- The bug is masked by ASan's redzones/quarantine and needs a plain build, or
  needs a different optimization level (`symbol_level`, `optimize_for_size`).
- The bug requires a specific feature flag (e.g. `v8_enable_sandbox`,
  `dcheck_always_on`, `enable_nacl`, `treat_warnings_as_errors = false`)
  that differs from the default.
- The bug requires a non-ASan component build for faster iteration
  (`is_component_build = true`), or a different target like `content_shell`
  or a unit test binary instead of `chrome`.

How to rebuild:

1. Edit `/opt/chromium/src/out/Asan/args.gn` (or create a new
   output directory like `out/Debug/` with its own `args.gn` so you don't
   clobber the existing ASan binary).
2. Regenerate the build files and build:
   ```
   cd /opt/chromium/src
   gn gen out/<dir>
   autoninja -C out/<dir> chrome     # or content_shell, unit_tests, etc.
   ```
   Incremental builds reuse cached object files; flipping a single GN arg is
   far cheaper than a cold build.
3. The new binary lands under `out/<dir>/` (e.g. `out/Debug/chrome`).

Keep the change minimal — only toggle the GN arg(s) actually required to
reproduce. Record in the PoC notes which build tweak was needed.
