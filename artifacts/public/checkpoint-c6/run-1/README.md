# Section 5 live-test run 20260831T125013Z

Status: **passed**
Plate: GJ01TT9911
Cameras requested: test-camera-a, test-camera-b, test-camera-c
Synthetic fixture: True
Started: 2026-08-31T12:50:13.921700+00:00

## Stages

- readiness check: passed (0.07s)
- synchronise catalogue / seed fixture: passed (20.52s)
- verify stream reachability: passed (4.37s)
- activate plate on watchlist: passed (0.0s)
- enable analytics on selected cameras: passed (1.03s)
- wait for sightings: passed (6.12s)
- verify alert: passed (0.0s)
- query journey: passed (0.0s)
- export and reconcile json/csv/html/pdf: passed (0.15s)
- record timing and resource metrics: passed (0.0s)
- stop workers and clean synthetic state: passed (0.06s)

## Contents

- `results.json` -- full machine-readable run record
- `run.log` -- redacted stage log (no raw feed URLs or secrets)
- `journey.json` / `journey.csv` / `journey.html` / `journey.pdf` -- journey export in every format
- `environment.json` -- interpreter, git commit, key package versions
- `checksums.json` -- sha256 of every file in this bundle
