Path to source code: /opt/firefox

Two ASan-instrumented binaries are pre-built in this image — pick the one whose execution surface matches the bug:

- Full Firefox browser (ASan):
    /opt/firefox/obj-ff-asan/dist/bin/firefox
    Use this for bugs that need a real browser (DOM, IPC, networking, media
    playback, graphics, rendering, content processes, XPCOM, devtools, etc.).
    Invoked via `firefox --headless`, xvfb, or the xrdp desktop in this image.

- SpiderMonkey JS shell (ASan):
    /opt/firefox/obj-js-asan/dist/bin/js
    Use this for bugs that are purely JS-engine-level (parser, bytecode
    emitter, interpreter, JIT/WASM, GC, SharedArrayBuffer / structured clone,
    self-hosted builtins, etc.). Much faster to invoke than the full browser
    and easier to script; prefer it whenever a bug can be reproduced with
    just JS code plus the shell's built-in `print`, `evaluate`, `gc`,
    `newGlobal`, etc.

Both builds live under the same source tree and are produced from separate
mozconfigs (`mozconfig` for the browser, `mozconfig-js` for the shell), so
grep/ripgrep/searchfox across `/opt/firefox/` returns the same
source regardless of which binary you intend to run.

## You may modify the build config and rebuild

The pre-built binaries are convenient defaults, **not constraints**. If a bug
only triggers under a different build configuration, you are free to edit the
mozconfig and rebuild. Examples of when to rebuild:

- The bug requires `--enable-debug` (debug assertions, `MOZ_ASSERT`, extra
  sanity checks, DEBUG-only codepaths).
- The bug requires a different sanitizer (UBSan, TSan, MSan) or combination.
- The bug is masked by ASan's redzones/quarantine and needs a plain build, or
  needs a different `--enable-optimize` level.
- The bug requires a specific feature flag (e.g. `--enable-jitspew`,
  `--enable-gczeal`, `--with-system-*`) that isn't on by default.
- The bug requires JIT disabled / enabled, WASM disabled / enabled, etc.

How to rebuild:

1. Edit the relevant mozconfig in `/opt/firefox/`:
   - `mozconfig` — full browser build (writes `obj-ff-asan/`).
   - `mozconfig-js` — SpiderMonkey JS shell (writes `obj-js-asan/`).
   - Or write a new mozconfig at a different path and point `MOZCONFIG` at it
     with a fresh `MOZ_OBJDIR` so you don't clobber the existing binaries.
2. Rebuild: `cd /opt/firefox && MOZCONFIG=<path> ./mach build`.
   Incremental builds reuse cached object files, so flipping flags like
   `--enable-debug` is much faster than a cold build.
3. The new binary lands under `<MOZ_OBJDIR>/dist/bin/`.

Keep the change minimal — only toggle the option(s) actually required to
reproduce. Record in the PoC notes which mozconfig tweak was needed.
