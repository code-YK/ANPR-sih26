# Security and Sensitive Data

This project concerns CCTV, law-enforcement workflows, watchlists, and potentially sensitive government infrastructure. Treat security and privacy as product requirements, not submission polish.

## Never commit

- camera or portal credentials;
- private feed/catalogue URLs or signed URLs;
- API keys, tokens, certificates, or session material;
- real watchlist or personal data;
- unauthorised CCTV frames, clips, screenshots, or derived biometrics;
- sensitive infrastructure diagrams, IP addresses, or logs; or
- test credentials intended for the screening committee.

Use synthetic data for development. Store approved secrets outside Git and reference them through documented environment-variable names or a secret manager.

## Reporting a vulnerability

Do not open a public issue containing exploit details or sensitive data. Notify the designated team security owner through the team's private channel. Include:

- affected component and revision;
- impact and prerequisites;
- minimal reproduction using synthetic data;
- redacted logs; and
- suggested containment if known.

The team should assign a security owner and private reporting channel before any public repository or hosted demo is created.

## Operational safeguards

- Apply least privilege and department/purpose-aware RBAC.
- Encrypt sensitive traffic and stored records.
- Segment media networks from operator/public services.
- Audit sensitive reads and state changes.
- Redact credentials and personal data from logs and evidence.
- Make retention configurable and minimise stored video/evidence.
- Time-bound and revoke demo credentials after evaluation.
- Perform a secret scan before every submission tag and before publishing code.

## Scope claims

Do not claim production security, privacy compliance, government-database integration, or biometric legality without evidence and explicit authorisation. The HLD must clearly distinguish current controls, tested controls, and proposed production controls.
