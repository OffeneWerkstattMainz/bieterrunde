---
name: verify
description: Run prek pre-commit checks and pytest to verify the codebase is clean and tests pass
---

Run the following commands in order from the project root and report results:

```bash
prek run
uv run pytest
```

Report any prek violations or test failures. If both pass, confirm everything is clean.
