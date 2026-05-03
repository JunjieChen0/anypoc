## Browser-Specific Rules

- **NO standalone C++ programs**: NEVER create a standalone C++ program that mimics the bug logic.
  Create real end-to-end bug manifestation in the actual browser, not a demonstration of the concept.
- The PoC must actually trigger the vulnerability in Firefox, not just illustrate how it could theoretically work.
- Only terminate the specific test processes you started (e.g., `pkill -x firefox`, `pkill -x Xvfb`, `pkill -f "http.server"`).
- **NEVER** run broad `pkill` patterns like `pkill firefox`, `pkill -f firefox`, `pkill python`, or `pkill -f python`. Your own parent process and orchestrator match these keywords — killing them will terminate this agent. Always use `-x` for exact name match or a highly specific `-f` pattern that cannot match the agent infrastructure.

## Build Instructions

If you added debug prints, you can rebuild firefox by:
```
cd /opt/firefox && ./mach build
```

## Notes

You can try to run an HTML file in headless mode.
You can also try to create screenshot.
You can also start simple local server and open url.
You MUST properly shutdown the server later or write scripts to automate the process.
