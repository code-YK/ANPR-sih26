# Verification evidence

Dated, redacted evidence packets recording **what was verified, when, and on which revision**.

## These files are history — do not edit them

Each packet is a record of a verification run at a point in time. They are deliberately **not** rewritten when framing, requirement IDs, or terminology change.

That means several of them use a `Model 1 / Model 2` vocabulary and `GOV-*` requirement IDs inherited from the programme this repository was originally built for. That vocabulary no longer exists in the current documentation ([ADR 0004](../docs/decisions/0004-sih26127-rescope.md)) — but editing a dated evidence file to match a newer narrative would make it worthless as evidence. They stay as written.

To map an old ID to a current one, use [ADR 0004](../docs/decisions/0004-sih26127-rescope.md) and [docs/requirements.md](../docs/requirements.md).

## Layout

```text
artifacts/
└── public/                 safe to share; redacted
    ├── checkpoint-c3/      registry, RBAC, audit, GIS, gap analysis, export
    ├── checkpoint-c6/      ANPR observation → alert → journey, multi-camera
    ├── checkpoint-c7/      reliability: interruption, recovery, codec matrix
    ├── checkpoint-c8/      second-machine reproduction, verification sweep
    └── checkpoint-c9/      feed status
```

Everything under `public/` has been reviewed as safe to share. There is no non-public tier in this repository; anything that could not be redacted was never committed.

## What a packet must contain

A packet is evidence only if a reader can tell whether to believe it:

- the exact command run,
- the revision it ran against,
- the environment (OS, Python, GPU where relevant),
- redacted output,
- **what was skipped or failed**, and
- an explicit statement of what the run does *not* prove.

That last point matters most. A packet claiming "ANPR verified" without saying whether the footage was labelled is not evidence of accuracy — only of the pipeline executing.

## Redaction rules

Never commit into a packet:

- credentials, tokens, or session material;
- private feed, catalogue, or signed URLs;
- real watchlist entries or personal data;
- observed vehicle identifiers from real footage;
- unauthorised CCTV frames, clips, or screenshots of government data.

Synthetic identifiers (`SYNTH-TEST-*`, `demo-cam-*`) are safe by construction. See [SECURITY.md](../SECURITY.md).
