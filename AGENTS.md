# Project instructions

## Mandatory live acceptance matrix

Before declaring any behavioral change ready, run live end-to-end acceptance against the deployed target container. Unit, integration, and mocked tests do not replace this matrix.

The minimum matrix is:

1. M365 direct/native path.
2. Router planning/tool path.
3. Studio planning/tool path.
4. Anthropic Messages API (the Claude Code-compatible protocol), including an API-level tool loop when the change can affect tools or continuation. Running the Claude Code client is not required.
5. OpenAI Responses API (the Codex-compatible protocol), including an API-level tool loop when the change can affect tools or continuation. Running the Codex client is not required.
6. Microsoft 365 Personal/Consumer provider path.

For streaming, tool-calling, continuation, session, or transport changes, exercise the affected behavior rather than only checking a health endpoint or one-shot text response. Record concrete pass/fail evidence for every matrix item.

When a new API protocol, provider, transport, planner, or runtime mode is introduced, add it to this live matrix in the same change and include it in every subsequent full acceptance run. Never silently omit a matrix item; if an environment prerequisite is unavailable, report the exact blocker and do not claim full acceptance.
