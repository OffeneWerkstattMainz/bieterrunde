---
name: verify
description: Run ruff format check and pytest to verify the codebase is clean and tests pass
---

Run the following commands in order from the project root and report results:

```bash
uv run ruff format --check .
uv run pytest
```

Report any formatting violations or test failures. If both pass, confirm everything is clean.
