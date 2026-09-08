# Setup

Local development setup for the Sentinel project. There are three independently
runnable components:

| Component | Path | Stack |
| --- | --- | --- |
| Backend API | `backend/` | FastAPI + PostgreSQL/PostGIS |
| Operator console | `frontend-v2/` | React + Vite (active UI) |
| Analytics / tracking | `multi-object-tracking/` | Python + PyTorch (CUDA) |

> `frontend/` (vanilla JS) and `frontend-v3/` are historical/experimental and
> are not required for a working setup. The production UI is `frontend-v2/`,
> which the backend serves at `/` when `frontend-v2/dist/` exists.

## Prerequisites

- **Python 3.13**
- **PostgreSQL 17** with the **PostGIS** extension
- **Node.js 20+** and npm
- **ffmpeg / ffprobe** on `PATH`
- (Analytics only) **NVIDIA GPU + CUDA 12.8+** for `multi-object-tracking/`
- (PDF export only) On macOS, WeasyPrint needs Homebrew's native libs on the
  loader path: run the server with `DYLD_LIBRARY_PATH=/opt/homebrew/lib`.

---

## 1. Backend (FastAPI)

From the repository root:

```bash
# create the virtualenv and install dependencies
python3.13 -m venv backend/.venv
# Windows:  backend\.venv\Scripts\pip install -r backend\requirements.txt
# macOS/Linux:
backend/.venv/bin/pip install -r backend/requirements.txt
```

Create the database once (PostGIS required):

```bash
createdb sentinel
psql -d sentinel -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

Configure the environment:

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env`:

- `DATABASE_URL` / `SYNC_DATABASE_URL` — point at your local Postgres.
- `SANDBOX_*` — obtain real sandbox endpoint values through the approved team
  channel. Leave blank for a no-auth / offline setup.
- `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` — set a real long demo secret.
- **Never commit a populated `.env`** — it is git-ignored.

Apply migrations and start the server:

```bash
# from backend/, with the venv active
alembic upgrade head
uvicorn app.main:app --reload
```

The API and (if built) the operator console are served at
<http://localhost:8000>.

---

## 2. Operator console (frontend-v2)

```bash
cd frontend-v2
npm install
npm run dev      # dev server with hot reload
```

Build a production bundle so the backend can serve it at `/`:

```bash
npm run build    # outputs frontend-v2/dist/
```

Scripts: `npm run dev`, `npm run build`, `npm run preview`, `npm run lint`.

---

## 3. Analytics / multi-object tracking

This component needs a CUDA-capable GPU. **Install PyTorch from the CUDA index
FIRST** — a plain `pip install torch` on Windows silently installs a CPU-only
wheel (~15x slower, no error):

```bash
cd multi-object-tracking
python -m venv .venv
# activate the venv, then:
pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision
pip install -r requirements.txt

# verify CUDA is available
python -c "import torch; print(torch.cuda.is_available())"
```

Optional number-plate recognition (`--plates`) pulls in
`opencv-python-headless`, which shadows `opencv-python` and breaks
`cv2.imshow`. Restore the GUI build afterward:

```bash
pip install fast-alpr
pip uninstall -y opencv-python-headless
pip install --force-reinstall --no-deps opencv-python
```

See `multi-object-tracking/README.md` for the individual worker/entrypoint
scripts.

---

## Notes

- Real footage, model weights (`*.pt`, `*.onnx`), recordings, and evidence
  crops are git-ignored and must stay local — see `.gitignore` and `SECURITY.md`.
- Further context: `README.md`, `backend/README.md`, `DESIGN.md`,
  `PROJECT_STATE.md`.
