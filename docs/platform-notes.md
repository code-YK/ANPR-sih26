# Platform notes — Windows and Linux

This codebase was originally developed on macOS and is now developed and demonstrated on **Windows and Linux**. That transition surfaced a cluster of defects that shared one root cause: code that is correct on POSIX and silently wrong on Windows.

They are all fixed. This document exists so the *pattern* is recognisable the next time one appears, and so nobody re-introduces one.

## The pattern

Three of the four defects below were invisible in development and only appeared at runtime on Windows — two of them with **no error message at all**. If something works on one teammate's machine and fails inexplicably on another, suspect this class first.

---

## 1. Device-convention mismatch — silent CPU fallback

**Symptom:** ANPR ran roughly 9× slower than expected, with no error.

`tracking_common.resolve_device()` returns **YOLO's** device convention — a bare index string `"0"` for CUDA, because that is what Ultralytics expects. Downstream code assumed the literal string `"cuda"`:

```python
if device == "cuda":          # False on every real GPU machine
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]
```

So ONNX Runtime silently fell through to `CPUExecutionProvider` — about 90 ms/crop instead of 10 ms.

**Fix:** treat anything that is not `"cpu"` or `"mps"` as a CUDA device index (`plates.py`).

**Why it matters beyond speed:** on short looping clips the slowdown starved tracks of sampled frames, so plates never accumulated enough votes to confirm before the track ended. It degraded *correctness*, not just throughput.

---

## 2. The same mismatch, as a hard crash

**Symptom:** every **person** ingest run failed instantly with exit code 1; vehicle runs were fine.

`person_embedding.load(device)` passed that same `"0"` straight to torch:

```python
backbone.to("0")   # RuntimeError: Invalid device string: '0'
```

Ultralytics accepts `"0"`; torch requires `"cuda:0"`. Vehicle ingest never loads the appearance model, so only person runs died — and they died before processing a single frame, which is why they showed 0 % progress and 0 tracks.

**Fix:** translate at the boundary in `person_embedding.py` (`_to_torch_device`), rather than changing `resolve_device()`, whose `"0"` contract every Ultralytics call site depends on.

---

## 3. `NamedTemporaryFile` — exclusive locking

**Symptom:** person-photo search failed with `PermissionError: [Errno 13] Permission denied`.

```python
with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
    tmp.write(image_bytes); tmp.flush()
    subprocess.run([..., "--image", tmp.name])   # child cannot open it
```

On Windows, `NamedTemporaryFile` holds the file open with **exclusive sharing**, so no other process can open it by name while the handle is alive. POSIX permits the concurrent open, which is why this worked for years on macOS.

**Fix:** `delete=False`, close the handle before spawning, and unlink in a `finally`.

---

## 4. `asyncio.create_subprocess_exec` — unsupported on `SelectorEventLoop`

**Symptom:** every recording upload stuck at `normalising` forever, with an **empty** error message.

The traceback, once captured from the running process:

```
File "app/pipeline/media.py", line 74, in probe_local_file
    proc = await asyncio.create_subprocess_exec(
File "asyncio/base_events.py", line 503, in _make_subprocess_transport
    raise NotImplementedError
NotImplementedError
```

Windows' `SelectorEventLoop` does not implement subprocess creation — only `ProactorEventLoop` does. And `str(NotImplementedError())` is `""`, which is why the failure surfaced as `"Normalisation failed: "` with nothing after the colon.

This was especially deceptive: a one-off `python script.py` picks up the correct Proactor default and works fine, so the bug looked upload-specific rather than process-wide. It only reproduced inside the running server.

**Fix:** don't depend on the loop implementation at all. `media.py` now runs ffprobe/ffmpeg via `asyncio.to_thread(subprocess.run, ...)` — the same pattern `investigate.py` already used for the person-search subprocess. A blocking call in a worker thread sidesteps the Proactor/Selector distinction entirely.

> Setting `WindowsProactorEventLoopPolicy` at the top of `main.py` was tried first and **did not work** — something later in the startup chain resets it. The thread-based approach is sturdier because it removes the dependency rather than fighting over it.

---

## Rules that follow

1. **Never call `asyncio.create_subprocess_exec`.** Use `await asyncio.to_thread(subprocess.run, ...)`. There are currently zero instances of the former in the codebase; keep it that way.
2. **Never hand a `NamedTemporaryFile`'s path to another process while the handle is open.** Close it first, `delete=False`, unlink in `finally`.
3. **Do not assume `resolve_device()` returns `"cuda"`.** It returns an index string. Translate at the boundary of any library that is not Ultralytics.
4. **Detached subprocesses on Windows need `CREATE_NEW_PROCESS_GROUP`.** Without it a plain `Popen` child shares the parent console and dies the instant that console gets Ctrl+C or closes — which meant restarting the backend silently killed every running analytics worker. See `_DETACHED` in `analytics.py` and `government_feed_relay.py`.
5. **An empty exception message is a clue, not a dead end.** `str(exc) == ""` usually means a bare `raise SomeError` with no arguments — `NotImplementedError` and `CancelledError` are the common culprits. Log `logger.exception(...)` so the traceback survives, and read it from `/api/logs/backend` if the process is not in a terminal you can see.

## Diagnosing a running backend

The app keeps an in-memory ring buffer of its own log output, streamed over SSE. When the server is running in a terminal you cannot read:

```bash
curl -s -N -b cookie.txt http://127.0.0.1:8000/api/logs/backend
```

That is how defect 4 above was finally identified — the traceback existed but was only visible in that stream.
