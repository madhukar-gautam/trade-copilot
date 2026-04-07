# Security policy

## Reporting a vulnerability

If you discover a security issue (especially anything involving credential leakage, token handling, or unintended network exposure), please do **not** open a public issue.

Instead, share a private report with:

- a clear description of the issue
- steps to reproduce
- impact assessment (what could be accessed/exfiltrated)
- any suggested fix

## Handling secrets

- Treat `config/settings.py` as sensitive. It is git-ignored by design.
- Rotate keys immediately if you suspect exposure.
- Do not paste tokens into logs, screenshots, or issues.

