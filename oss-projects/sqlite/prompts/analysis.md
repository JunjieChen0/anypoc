# Bug Report to Reject

If a bug report satisfy any of the following condition, immediately reject it without further investigation:

1. About `tool/fuzzershell.c`
2. The bug is in any of the test files (e.g `test/fork-test.c`)
3. Triggering the bug requires unrealistic conditions (e.g. setting configurations to unreasonable values where no real developer would set)
