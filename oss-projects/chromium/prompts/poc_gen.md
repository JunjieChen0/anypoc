## Browser-Specific Rules

- **NO standalone C++ programs**: NEVER create a standalone C++ program that mimics the bug logic.
  Create real end-to-end bug manifestation in the actual browser, not a demonstration of the concept.
- The PoC must actually trigger the vulnerability in Chromium, not just illustrate how it could theoretically work.
- Only terminate the specific test processes you started (e.g., `pkill -x chrome`, `pkill -x Xvfb`, `pkill -f "http.server"`).

## Build Instructions

If you need to build chromium again (e.g. use a different sanitizer, add debug print, etc.),
the build process for chromium is:
```
/opt/chromium/src/out/Asan/args.gn   # This file contains the build configuration

/opt/chromium/tools/depot_tools/gn gen out/Asan   # This command generates build files

/opt/chromium/tools/depot_tools/autoninja -C out/Asan chrome # This command compiles the chromium
```

## Notes

You can try to run an HTML file in headless mode.

You can also start simple local server and open url.

You can use remote debug port to send events to simulate user interaction.

You MUST properly shutdown the server later or write scripts to automate the process.

You CANNOT use gtest to simulate unrealistic situations!
