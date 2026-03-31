# Reject Bugs

If the bug reports satisfy any of the following condition, reject it without further exploration:

1. Involved building custom module
2. Requires OOM to trigger
3. Use unrealistic configurations
4. Might require race condition to trigger (e.g. need free/malloc to hold an arena lock)
