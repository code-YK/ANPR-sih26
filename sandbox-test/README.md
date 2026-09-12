# Catalogue probe client

A small standalone diagnostic for inspecting an HTTP camera catalogue and checking that a camera's stream actually opens — **before** onboarding it into the registry.

It is intentionally separate from `backend/` and `multi-object-tracking/`: it holds no database credential, writes nothing, and can be run against a source that is not yet trusted.

## When to use it

- A camera source is unreachable and you need to tell *catalogue is down* apart from *this camera is down* apart from *this network blocks RTSP*.
- You are evaluating a new source before writing a connector adapter for it.
- Live preview fails and you need to know whether the stream opens outside the browser at all.

For anything routine, use the backend's own probe endpoints instead — they record health history, respect department scoping, and keep the result visible in the operator console.

## Usage

```bash
python sentinel_client.py list                      # inspect the catalogue
python sentinel_client.py list --save catalogue.json
python sentinel_client.py frame 2                   # one diagnostic still
```

The host comes from the `SENTINEL_HOST` environment variable. **Never** hard-code an endpoint into this file or into a command pasted somewhere shareable.

## Deliberate limitations

- **It reads camera URLs from the catalogue** rather than reconstructing them from a pattern, so it cannot drift from the source of truth.
- **It forces RTSP over TCP** and reconnects with backoff, matching the workers' behaviour — if it opens and a worker does not, the difference is in the worker, not the network.
- **There is no clip-recording command, on purpose.** Live feeds are real-time-only and must not be downloaded or retained as footage.
- **Frame capture is an exceptional diagnostic.** It requires separate approval for the specific purpose and retention. This utility does not grant that approval, and a captured frame must never be committed.

## Requirements

`opencv-python` and `requests`. It can run from either project virtualenv, or from a standalone one — it imports nothing from `backend/` or `multi-object-tracking/`.

## Scope note

SIH26127 supplies no organiser sandbox or dataset. This client survives from an earlier programme and remains useful as a generic catalogue/stream probe. The directory name is historical; see [ADR 0004](../docs/decisions/0004-sih26127-rescope.md).
