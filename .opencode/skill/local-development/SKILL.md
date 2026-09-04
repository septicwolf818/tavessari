---
name: local-development
description: Provides guidance for local development, prioritizing edits over rewrites and avoiding pkill.
---

# Local Development

When performing software engineering tasks, follow these rules:

- **Prioritize Edits Over Rewrites**: Whenever possible, use fine-grained edits to modify existing code rather than rewriting entire files or large blocks of code. This minimizes noise in diffs and reduces the risk of introducing regressions.
- **Avoid `pkill`**: Do not use the `pkill` command to terminate processes. Instead, use more precise methods like `kill <PID>` or specific target signals to ensure only the intended processes are stopped and to avoid side effects.
