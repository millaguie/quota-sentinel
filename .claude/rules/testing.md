---
description: Testing patterns and conventions
globs: ["**/*test*", "**/test_*", "**/*_test.*", "**/*.spec.*"]
---

# Testing Conventions

- Every new feature must have tests before the PR is considered complete
- Test names should describe the behavior: `test_returns_404_when_user_not_found`
- Prefer integration tests over unit tests for I/O-heavy code
- Mock external services, not internal modules
- Each test should be independent — no shared mutable state between tests
- Use factories or fixtures for test data, not hardcoded values
- Assert specific values, not just truthiness
- Keep tests close to the code they test
