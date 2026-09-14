# Setup

Local development setup for **SIH26127 / Sentinel**. Everything here is verified on **Windows 11** and written to work identically on **Linux**. There is no macOS path — the team runs Windows and Linux only.

There are three independently runnable components:

| Component | Path | Stack |
| --- | --- | --- |
| Backend API | `backend/` | Python 3.11 · FastAPI · PostgreSQL/PostGIS |
| Operator console | `frontend-v3/` | React 19 · Vite 8 — **the served UI** |
| Analytics / tracking | `multi-object-tracking/` | Python 3.11 · PyTorch (CUDA) |

> `frontend-v2/` is the previous console, kept as reference and still runnable on port 5173. `frontend/` is the original vanilla UI and is not served. The backend serves `frontend-v3/dist` at `/`.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | **3.11** | Both virtualenvs. Not 3.12+ — see *Why 3.11* below |
| PostgreSQL + PostGIS | 16 or newer | Or use the team's hosted database (see step 2) |
| Node.js | `^20.19` or `>=22.12` | Required by Vite 8. Verified on 24.19.0 |
| FFmpeg / ffprobe | any recent | **Required, global install, on `PATH`** — see *FFmpeg* below |
| NVIDIA GPU + CUDA | 12.8+ | Analytics only. **Required** for RTX 50-series (Blackwell, sm_120) |
| MediaMTX | any recent | Needed for live preview and government/demo modes |

### FFmpeg

Not optional and not something `pip install` can provide — it is a native
binary, not a Python package, so it is unrelated to either `.venv` and must
be installed once at the OS level, the same tier as installing Python or
Node itself. Four things call it directly and have no fallback if it is
missing: camera onboarding (probing + survey stills), Investigate upload
normalisation, and the WebRTC/WHEP live preview.

It must be on `PATH` — unlike MediaMTX below, there is no `FFMPEG_BIN`
setting to point at a custom location. If it's missing or not on `PATH`,
every one of those features fails the same way MediaMTX does when
misconfigured: `FileNotFoundError: [WinError 2] The system cannot find the
file specified` (Linux: `FileNotFoundError: [Errno 2] No such file or
directory`).

- **Windows:** `winget install Gyan.FFmpeg`, then open a **new** terminal
  (PATH only updates for new shells) and confirm with `ffmpeg -version`. No
  winget: download the "full" build from
  [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/), unzip
  anywhere, and add its `bin/` folder to your user `PATH` manually.
- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) puts both `ffmpeg`
  and `ffprobe` on `PATH` directly.

### Why 3.11

The whole codebase is verified against **Python 3.11.9**. Do not assume a newer interpreter works: one file previously used an f-string containing a backslash, which is valid only on 3.12+ and fails to even parse on 3.11 — it has been fixed, but the lesson stands. Pin 3.11 across the team so everyone hits the same behaviour.

```bash
# Windows
py -3.11 --version
# Linux
python3.11 --version
```

---

## 1. Backend

### Create the virtualenv and install

**Windows (PowerShell)**
```powershell
py -3.11 -m venv backend\.venv; backend\.venv\Scripts\python.exe -m pip install --upgrade pip; backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
```

**Linux (bash)**
```bash
python3.11 -m venv backend/.venv && backend/.venv/bin/pip install --upgrade pip && backend/.venv/bin/pip install -r backend/requirements.txt
```

### 2. Configure the database

```bash
cp backend/.env.example backend/.env
```

Then edit `backend/.env`. You have two options.

**Option A — the team's hosted database (current default).** Ask the project owner for the `DATABASE_URL` and `SYNC_DATABASE_URL` values. Two things about them are load-bearing:

- Use the **direct** endpoint, never the `-pooler` one. PgBouncer transaction pooling breaks asyncpg's prepared statements.
- The two URLs use different SSL spellings on purpose — `?ssl=require` for asyncpg, `?sslmode=require` for psycopg2. That is not a typo; they are different libraries with different parameter names.

**Option B — local PostgreSQL.**

**Windows (PowerShell)**
```powershell
createdb sentinel; psql -d sentinel -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

**Linux (bash)**
```bash
sudo -u postgres createdb sentinel && sudo -u postgres psql -d sentinel -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

Then set both URLs to your local instance. Swapping between hosted and local is a **two-line `.env` change** — nothing in the code hard-codes a connection string.

Also set in `.env`:

- `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` — seeded at startup when both are present; password ≥ 10 characters.
- `WORKER_API_TOKEN` — the service token analytics workers use to post observations. Separate from human sessions on purpose.
- `MEDIAMTX_BIN` — absolute path to your `mediamtx` binary (step 5). **Per-machine**; do not copy someone else's.
- `AUDIT_ARCHIVE_DIR` — leave blank for ordinary development.

**Never commit a populated `.env`.** It is git-ignored.

### 3. Migrate and run

**Windows (PowerShell)**
```powershell
cd backend; .\.venv\Scripts\alembic.exe upgrade head; .\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

**Linux (bash)**
```bash
cd backend && ./.venv/bin/alembic upgrade head && ./.venv/bin/uvicorn app.main:app --reload --port 8000
```

### 4. Seed cameras

The government-camera registry is what government mode swaps stream URLs on — without these rows the toggle has nothing to work with.

**Windows (PowerShell)**
```powershell
cd backend; .\.venv\Scripts\python.exe scripts\seed_government_cameras.py; .\.venv\Scripts\python.exe scripts\seed_government_cameras.py --verify
```

**Linux (bash)**
```bash
cd backend && ./.venv/bin/python scripts/seed_government_cameras.py && ./.venv/bin/python scripts/seed_government_cameras.py --verify
```

This is safe to re-run: it updates metadata and deliberately **never** touches stream-endpoint columns, so re-seeding while government mode is active cannot pull the relay URLs out from under it.

An additional safe synthetic dataset is available via `scripts/seed_synthetic_demo.py` — see [backend/fixtures/README.md](backend/fixtures/README.md).

---

## 5. MediaMTX

Needed for the WebRTC/WHEP preview and for both demo and government modes. **It is not vendored** — the Windows `.exe` is useless on Linux and vice versa.

Download: **[github.com/bluenviron/mediamtx/releases](https://github.com/bluenviron/mediamtx/releases)** — latest release, the platform-specific `.zip`/`.tar.gz` (not the Docker image).

- **Windows:** download `mediamtx_*_windows_amd64.zip`, unzip to `tools/mediamtx/` (so `tools/mediamtx/mediamtx.exe` exists), then set `MEDIAMTX_BIN=E:\path\to\repo\tools\mediamtx\mediamtx.exe` in `backend/.env`.
- **Linux:** download `mediamtx_*_linux_amd64.tar.gz`, extract to `tools/mediamtx/` (so `tools/mediamtx/mediamtx` exists), `chmod +x` it, then set `MEDIAMTX_BIN=/path/to/repo/tools/mediamtx/mediamtx` in `backend/.env`.

Its absence is non-fatal for the preview — the backend logs a warning and every camera stays viewable over HLS — but government and demo modes will refuse to start without it.

**Having the file is not enough — `MEDIAMTX_BIN` must also be set.** The setting defaults to the bare word `mediamtx`, which only works if it is on your system `PATH`; `tools/` is gitignored (each machine's binary stays local, see step 6), so a fresh clone has the folder but not the env var. The symptom is `FileNotFoundError: [WinError 2] The system cannot find the file specified` when toggling demo/government mode, even with `mediamtx.exe` sitting right there in `tools/mediamtx/` — it means `backend/.env` is missing (or has a wrong/relative) `MEDIAMTX_BIN` line. Fix: add the absolute path as above, using this machine's own drive letter and repo path, then restart the backend.

Three MediaMTX instances can run side by side on deliberately distinct ports:

| Instance | RTSP | HLS | API |
|---|---|---|---|
| WebRTC/WHEP preview | 8554 | — | 9997 |
| Government mode relay | 8556 | 8890 | 9999 |
| Demo mode relay | 8557 | 8888 | — |

---

## 6. Operator console (frontend-v3)

```bash
npm --prefix frontend-v3 ci
npm --prefix frontend-v3 run dev
```

Opens on **port 5174**, fixed via `strictPort`. That is not arbitrary: video is fetched cross-origin from the backend even in development, so this origin must be a known entry in the backend's CORS allowlist. Letting Vite auto-increment the port would silently break every video fetch with a CORS error.

Build a production bundle so the backend serves it at `/`:

```bash
npm --prefix frontend-v3 run build
```

Scripts: `dev`, `build`, `preview`, `lint`.

To run the older console alongside it: `npm --prefix frontend-v2 run dev` (port 5173, also allow-listed).

---

## 7. Analytics / multi-object tracking

Needs a CUDA-capable GPU and **its own virtualenv** — do not reuse `backend/.venv`.

**Install PyTorch from the CUDA index FIRST.** A plain `pip install torch` on Windows silently installs a CPU-only wheel — roughly 15× slower with no error message. On RTX 50-series (Blackwell, sm_120) cu128 or newer is mandatory, not advisory.

**Windows (PowerShell)**
```powershell
py -3.11 -m venv multi-object-tracking\.venv; multi-object-tracking\.venv\Scripts\pip.exe install --index-url https://download.pytorch.org/whl/cu128 torch torchvision; multi-object-tracking\.venv\Scripts\pip.exe install -r multi-object-tracking\requirements.txt
```

**Linux (bash)**
```bash
python3.11 -m venv multi-object-tracking/.venv && multi-object-tracking/.venv/bin/pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision && multi-object-tracking/.venv/bin/pip install -r multi-object-tracking/requirements.txt
```

### Verify CUDA actually works

`torch.cuda.is_available()` alone is not enough — check that your architecture is in the compiled arch list and that a kernel really launches:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(0), torch.cuda.get_arch_list())"
```

Expected on an RTX 5060: `2.11.0+cu128 True (12, 0) [... 'sm_120']`.

### Verify OpenCV kept its GUI build

`fast-alpr` pulls in `opencv-python-headless`, which shares the same `cv2/` directory as `opencv-python`. Whichever pip writes last wins, so `cv2.imshow` can break silently:

```bash
python -c "import cv2; cv2.namedWindow('t'); cv2.destroyAllWindows(); print('GUI OK')"
```

If that fails:
```bash
pip uninstall -y opencv-python-headless && pip install --force-reinstall --no-deps opencv-python
```

See [multi-object-tracking/README.md](multi-object-tracking/README.md) for the individual worker scripts.

---

## External assets not in Git

Three things are **required to run the full demo** but are deliberately not committed. Get them from the project owner out of band.

| Asset | Size | Without it |
|---|---|---|
| `backend/.env` | — | **Nothing runs.** Share securely — never Git, never chat |
| `recorded-streams/` (`*.mp4` + `*.json` sidecars) | ~673 MB | Government mode has nothing to relay |
| `multi-object-tracking/*.pt`, `*.onnx` | ~167 MB | `yolo11x`/`yolo11n` auto-download, but **`best.pt` does not** — suspicious-activity mode fails |
| `fixtures/live-test/` | ~1 MB | Demo mode cannot start |

When sharing `recorded-streams/`, **exclude `_relay/`** — it is machine-local runtime state (PID files, a generated `mediamtx.yml` with absolute paths, ffmpeg logs) and stale PIDs there can confuse the relay's liveness check.

`tools/` is per-OS; see step 5 rather than copying someone else's.

---

## Verify the whole stack

```bash
# 1. backend responds (auth-gated, so a 401 body is a healthy sign)
curl http://127.0.0.1:8000/api/health

# 2. console builds
npm --prefix frontend-v3 run build

# 3. every Python file parses under 3.11
backend/.venv/Scripts/python.exe -m compileall -q backend/app backend/scripts multi-object-tracking
```

Then sign in at <http://localhost:5174> (dev) or <http://127.0.0.1:8000> (built) and turn on **Access admin → Advanced → Government mode** to see recorded feeds flow through the real pipeline.

---

## Platform notes

Several defects only appear on Windows, because this codebase was originally developed on macOS. They are fixed, but if you hit something similar, [docs/platform-notes.md](docs/platform-notes.md) records the pattern and the fixes.

## Notes

- Real footage, model weights, recordings, and evidence crops are git-ignored and must stay local — see `.gitignore` and [SECURITY.md](SECURITY.md).
- Further context: [README.md](README.md), [backend/README.md](backend/README.md), [docs/hld.md](docs/hld.md), [PROJECT_STATE.md](PROJECT_STATE.md).
