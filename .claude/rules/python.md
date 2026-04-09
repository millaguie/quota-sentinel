---
description: Python code conventions for quota-sentinel
globs: ["**/*.py"]
---

# Python Conventions

- Use type hints on all function signatures
- Prefer f-strings over .format() or % formatting
- Use `from __future__ import annotations` for forward references
- Follow PEP 8 naming: snake_case for functions/variables, PascalCase for classes
- Use pathlib.Path over os.path
- Prefer dataclasses or NamedTuple over plain dicts for structured data
- Use context managers for resource management (files, connections)
- Imports: stdlib first, third-party second, local third (enforced by ruff isort)
