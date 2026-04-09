---
description: Security rules — always active
globs: ["**/*"]
---

# Security Rules

- NEVER hardcode secrets, API keys, tokens, or passwords in source code
- NEVER commit .env files, credentials, or private keys
- Validate and sanitize all external input (user input, API responses, file contents)
- Use parameterized queries — never concatenate SQL strings
- Escape output to prevent XSS (use framework-provided mechanisms)
- Use HTTPS for all external API calls
- Set appropriate CORS headers — never use wildcard (*) in production
- Review dependencies before adding — prefer well-maintained, audited packages
- Log security events (auth failures, permission denials) but never log sensitive data
