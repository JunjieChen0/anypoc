## Process Termination Safety

- **NEVER** run broad `pkill` patterns like `pkill firefox`, `pkill -f firefox`, `pkill python`, or `pkill -f python`. Your own parent process and orchestrator match these keywords — killing them will terminate this agent. Always use `-x` for exact name match (e.g., `pkill -x firefox`, `pkill -x Xvfb`) or a highly specific `-f` pattern that cannot match the agent infrastructure.
