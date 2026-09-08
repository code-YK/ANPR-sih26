# C3 GIS coverage-layer browser verification — 2026-08-31

## Scope

Closes the remaining gap explicitly flagged in
`gis-coverage-layer-2026-08-31.md` ("a teammate should run the authenticated
map in a permitted browser, confirm the type/live filters and the coverage
toggle/radius selector"). That artifact only covered lint/build; this one
drives the actual rendered map.

- Base revision: `63f4f9a` (post-merge `main`, includes both the GIS
  coverage layer and the Section 5 live-test Phase 2 work)
- Method: Playwright against the running dev server
  (`frontend-v2` on :5173, `backend` on :8000), authenticated as the seeded
  super admin
- No camera endpoint, credential, or raw stream URL appears in any
  screenshot below -- only department/location/marker-colour and the
  synthetic camera names already visible in the registry

## Result

- `/registry/map` loads and renders the Leaflet/OpenStreetMap base layer
  with camera markers.
- Camera-type filter (`All camera types` / `Fixed` / `PTZ` / `Analog` /
  `IP`) and live-status filter (`Any live status` / `Live` / `Offline`)
  both enumerate correctly and visibly change the marker set when applied.
- "Indicative coverage" checkbox + radius select (`100 m` / `250 m` /
  `500 m`) both work: toggling it on changes the hint text to `Marker
  colour: green live, red offline/unreachable, grey unknown. 11 live,
  geocoded camera(s) have a 500 m planning ring; it is not a measured
  field of view.` -- the count (11) matches the live+geocoded subset of
  cameras at the time of the check, confirmed against `coverageCandidates`'s
  own filter (`is_live === true` and geocoded) in `MapView.jsx`.
- The unplaced-cameras panel lists every camera whose geocode failed
  (visible in the screenshot), consistent with the map never silently
  dropping an ungeocoded camera.

## Boundary

Same-host verification, not a second-machine teammate reproduction (that
remains open per `clean-clone-2026-08-31.md`). Visual/rendering check only
-- this does not re-verify the underlying geocode-confidence or health-state
logic already covered by other C3 evidence in this directory.
