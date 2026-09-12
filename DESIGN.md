# Sentinel — Operator Console Design Direction

Status: **Implemented and merged to `main`. Not yet checkpoint evidence.**

Date: 2026-08-30 (direction accepted); implementation recorded 2026-08-30

Owners: Team

This document states the visual and interaction direction for the React
operator console (`frontend-v2/`), the token system that expresses it, and the
rules for the components that recur across every view.

All six adoption steps in §13 are merged on `main`. Four details remain
incomplete or only partially implemented for reasons recorded inline:
§3.1's `withheld` state, §3.2's "outside your grants" tile, §6.1's global
queued-worker/cap summary, and §8's client-side gap-analysis meter. Where this
document and the code disagree, the code is right and the gap is noted in
place.

No browser evidence is recorded. Every section was verified against static
harnesses built from the real compiled CSS, because this environment has no
credentials to reach the authenticated views. Redacted browser evidence and a
teammate clean-clone review are still required before any of this is cited at
a checkpoint. `PROJECT_STATE.md` remains the authority on what exists.

Implementation follows the `frontend-standards` skill: HSL tokens, a `rem`
scale on a 4px baseline, dual-shadow depth on interactive surfaces, optical
button padding, and native HTML elements in place of JS widgets. §14 records
the one place this document knowingly departs from it, and why.

Related: [`docs/architecture.md`](docs/architecture.md),
[`docs/operator-console-build-spec.md`](docs/operator-console-build-spec.md),
[ADR 0003](docs/decisions/0003-department-rbac.md),
[`docs/requirements.md`](docs/requirements.md).

---

## 1. What the console is for

One person, on shift, watching roughly 30 to 50 live-simulated feeds from five
government departments, needs to answer three questions faster than they can
articulate them:

1. **What does the system know?** — a plate was read, a camera is live, a
   vehicle passed here at this time.
2. **How well does it know it?** — confirmed by a reader, inferred from a place
   name, approximate, or never surveyed at all.
3. **What can it not see?** — cameras that cannot resolve a plate, stops with
   no coordinates, departments outside the operator's grants, streams that
   dropped and came back as a different session.

Every mainstream dashboard answers the first question and quietly suppresses
the other two. Sentinel is architecturally committed to answering all three:
the registry carries `metadata_confidence` so that "an inference must never
render as if it were a confirmed fact"
([`Badge.jsx`](frontend-v2/src/components/Badge.jsx)); the HLS player reports
its own reconnect count because "presenting it as one unbroken feed would
misrepresent it" ([`docs/operator-console-build-spec.md`](docs/operator-console-build-spec.md));
the journey endpoint returns `restricted_stops` and `unplaced_stops` rather
than silently dropping either.

That commitment is the design brief. **The console's job is to make the limits
of the system's knowledge as legible as its knowledge.**

## 2. The problem this replaced

*(The state of `main` before this direction was implemented. Retained because
the amber collision below is the reason the certainty grammar exists.)*

The look was ported like-for-like from the original vanilla UI and had
no point of view: a `#f5f6f8` ground, a default `#1c5cb8` blue, the system font
stack, 6–8px radii, and pastel pill badges. It read as generic administrative
CRUD. Under `GOV-SUB-003` the judged artifact is a screen recording of the real
software, so the console's appearance is a submission deliverable, not polish.

It also carried one substantive defect. In
[`style.css`](frontend-v2/src/style.css), amber (`--warn`) meant three
unrelated things at once:

| Amber meant | Kind of statement |
|---|---|
| `approximate` geocode, `inferred` metadata | how well we know a fact |
| `medium` alert severity | how urgent a situation is |
| stream reconnecting, worker queued | how the machinery is behaving |

An operator scanning a wall could not tell which meaning a given amber mark
carried. The same collision affected green (`live` / `viable` / `resolved`) and
red (`offline` / `high severity` / `unplaced`). This was not a palette problem;
it was a missing distinction, and resolving it is the spine of this direction.
Fixed in step 2: the epistemic senses moved to texture, leaving each colour one
meaning.

## 3. Direction

**Texture carries epistemics. Colour carries urgency. They never mix.**

Two independent channels, each with one job:

- **How a fact is known** is expressed structurally — through rules, hatching,
  weight, and typographic absence. It survives greyscale, colour-blindness, and
  video compression.
- **How urgent something is** is expressed in colour, and colour is reserved
  for nothing else. When something on screen is red, it is because a person
  must act.

The console is a single dark instrument surface. Video is the primary content,
and the page it had been framed by was near-white, which fought it; CCTV
footage, much of it at night, belongs on a dark ground. Dark also lets the four
urgency hues sit at low saturation and still read, which keeps the wall calm
until something is genuinely wrong.

### 3.1 The signature: the certainty ledger

One grammar for epistemic state, applied identically to a video tile, a table
cell, a map marker, and a journey stop. Four states, distinguished by texture —
**and every one of them always carries its word.** The texture makes a 30-row
table scannable at a glance and survives greyscale; the label means nothing
requires a legend to read.

```
CONFIRMED    │ Ahmedabad Zone 3        solid 2px rule, full-strength text
INFERRED     ┊ Rajkot Ring Rd  inferred    dashed 2px rule, text at 80%
UNKNOWN      │ —  not surveyed         solid rule, em-rule for the value
WITHHELD     ▨ ▨▨▨▨▨  withheld         hatched block, space kept and counted
```

Rules that make it a system rather than a decoration:

- **The label is not optional.** Texture is the fast channel and the word is the
  certain one. A mark that carries only texture fails "Don't Make Me Think"; a
  mark that carries only a word is unscannable at 30 rows. Both, always. The
  cost is horizontal space, which is why the label face is condensed (§5).
- **Unknown shows an em-rule for the value.** A camera never surveyed renders
  `—` where the value would be, labelled `not surveyed`. The glyph reads as
  absence instantly; the label says which kind of absence.
- **Withheld occupies its space.** RBAC redaction is hatched, never omitted and
  never collapsed. The operator sees that something exists there and that they
  are not cleared for it. This is already true in the API (`restricted_stops`)
  and must be true on screen.
  > **Built, but unused.** `CertaintyMark`'s `withheld` variant exists and is
  > styled. No call site renders it, because no endpoint currently marks a
  > *field* as hidden-by-grant rather than merely absent — `/journey`'s
  > `restricted_stops` is a row-level count, not a per-field signal. Wiring it
  > needs a backend change, not a frontend one.
- **Inferred is never louder than confirmed.** Same size, same colour, dashed
  rule and slightly reduced strength. An inference is a real fact about a real
  camera; it is simply held with less confidence.
- **Every inferred value states its derivation** on hover and focus, in the same
  words the backend used.

### 3.2 The risk worth taking: the absence grid

On the Live view, cameras the console cannot show are **not** omitted from the
wall and **not** rendered as identical grey boxes. Each kind of nothing gets
its own persistent texture in the grid position the camera occupies, with its
word on the tile:

```
┌──────────┬──────────┬──────────┐
│  ▶ live  │  ▶ live  │ ╱╱╱╱╱╱╱╱ │  ╱  no stream endpoint
├──────────┼──────────┼──────────┤
│  ▶ live  │ ▨▨▨▨▨▨▨▨ │  ▶ live  │  ▨  outside your grants
├──────────┼──────────┼──────────┤
│ ┈┈┈┈┈┈┈┈ │  ▶ live  │  ·  ·  · │  ┈  live, cannot read plates
└──────────┴──────────┴──────────┘     ·  beyond the concurrency cap
```

The operator reads the shape of the estate's blindness directly off the wall,
and a judge watching the recording sees gap analysis (`GOV-M1-006`), RBAC
(`GOV-NFR-001`), and load pacing (`GOV-ING-012`) demonstrated without a slide.
The risk is that a wall of textures looks broken. It is controlled by keeping
every texture low-contrast against the panel ground — absence should be quiet,
present, and countable, never alarming. If a texture ever draws the eye before
a live tile does, it is too strong.

Spend the boldness here. Everything else stays disciplined.

> **Two of the four shipped.** `no stream endpoint` (diagonal hatch) and
> `beyond the concurrency cap` (dot grid) are live.
>
> `outside your grants` is **not buildable as specified**. `GET /api/cameras`
> filters at the query level — `Camera.department.in_(allowed)` — so cameras
> outside a grant never reach the browser and the frontend cannot know they
> exist. It needs the backend to return a hidden count, the way `/journey`
> already returns `restricted_stops`. This is the single most demo-valuable
> gap left in the console (`GOV-NFR-001`, RBAC visibly enforced).
>
> `live, cannot read plates` is **deliberately not** a tile texture. A camera
> that is streaming should show its video; covering working footage with a
> texture hides the one thing a video wall exists for. That state is carried
> by the `AnprBadge` in the tile overlay instead, which renders both surveyed
> outcomes.

## 4. Colour

All colour is HSL so the palette stays programmable. The neutral ramp is one
hue and one saturation with only lightness varying — eight stops generated from
two variables, not eight hand-picked values.

The ground hue is a graphite with a slight green-grey cast rather than a
blue-black or a neutral charcoal. Blue-black grounds push CCTV's blue-white IR
footage and Leaflet's blue map tiles toward the chrome; a faintly warm-neutral
ground holds them apart as content.

```css
:root {
  /* One hue and one saturation generate the entire neutral ramp. */
  --ground-h: 158;
  --ground-s: 8%;

  --ink-900:  hsl(var(--ground-h) var(--ground-s) 6%);   /* page, video letterbox */
  --ink-800:  hsl(var(--ground-h) var(--ground-s) 10%);  /* panels, table surface */
  --ink-700:  hsl(var(--ground-h) var(--ground-s) 13%);  /* raised, hover, focus */
  --ink-600:  hsl(var(--ground-h) var(--ground-s) 19%);  /* rules, borders */

  --haze-400: hsl(var(--ground-h) var(--ground-s) 51%);  /* labels, absent values */
  --haze-300: hsl(var(--ground-h) var(--ground-s) 67%);  /* secondary text */
  --haze-100: hsl(var(--ground-h) var(--ground-s) 88%);  /* primary text */

  /* Urgency — the only colours in the system. */
  --nominal:  hsl(158 43% 56%);  /* live, healthy, resolved */
  --degraded: hsl(36  72% 57%);  /* reconnecting, queued, needs attention */
  --critical: hsl(4   75% 60%);  /* open alert, offline, failed */
  --entity:   hsl(207 49% 71%);  /* plate and entity references only */
}
```

Two relationships in this palette are worth keeping deliberately:

- **`--nominal` is the ground hue brought to life.** Both sit at H 158; the
  healthy state is the console's own ground at full saturation rather than a
  foreign green. Nothing else in the palette shares the ground hue.
- **`--degraded` → `--nominal` is almost exactly a +120° rotation** (36° → 158°).
  The `frontend-standards` rotation formula and the semantics agree here by
  coincidence, which is worth noting but is not the reason for either value.

Why the hues are not fully generated by rotation: `--critical` must be red and
`--nominal` must be green, because those are conventions an operator brings
with them and a formula would break. The formula's discipline is applied where
it costs nothing — the neutral ramp — and set aside where it would trade a
convention for symmetry.

Further discipline:

- **Four hues, total.** `--entity` is not an accent; it is the single colour of
  a clickable identity (a plate, a camera id) and appears nowhere else.
  Selection and interactive state are expressed as surface and depth (§6), not
  as a fifth hue.
- **`--degraded` is sodium amber**, the colour of the street lighting in the
  footage itself, not a generic warning yellow.
- **Colour never encodes confidence.** An approximate geocode is not amber. It
  is a dashed rule and the word `inferred`.
- **Saturation stays low.** On a dark ground, saturated hues bloom and read as
  emergency. Reserve full-strength `--critical` for open, unacknowledged alerts
  and nothing else.
- Colour is deliberately unremarkable here. In a safety-critical console,
  colour is load-bearing for urgency, so it is not where the personality lives.
  The personality lives in the texture system and the type.

Contrast floor: `--haze-100` on `--ink-800` and every urgency hue on `--ink-800`
must clear WCAG AA at the sizes used. Verify, do not assume.

## 5. Typography

Two faces, both open source, both self-hosted.

| Role | Face | Use |
|---|---|---|
| Display / label / body | Instrument Sans | view titles, eyebrows, column headers, certainty labels, prose, form labels, empty states |
| Data | IBM Plex Mono | every machine identifier — plates, camera ids, timestamps, coordinates, confidences, epochs, reconnect counts |

Why this:

- **Open source**, which `GOV-CORE-005` requires of the judged path.
- One interface face rather than a display/body pair. The split had been
  carrying a *condensed* display face, and condensed headings never had the
  width to anchor a page — the hierarchy problem in §5.2 was doing the real
  damage, but the narrowness compounded it.
- Contemporary without being playful. It reads as a current product rather
  than as developer tooling, which is what the console is judged as.
- Mono stays IBM Plex Mono. It carries plates, timestamps and coordinates,
  where distinguishable figures and a true tabular set matter more than
  matching the UI face.

> **Revised 2026-09-01.** This was IBM Plex Sans Condensed + IBM Plex Sans,
> chosen partly because **IBM Plex Sans Gujarati** is a matched sibling, making
> bilingual labelling a font swap rather than a redesign. In use the Plex
> pairing read narrow and corporate-technical, and it was replaced.
>
> **That trade is real and unresolved:** Instrument Sans has no Gujarati.
> Bilingual labelling would now need a second family — Noto Sans Gujarati as
> the neutral option, or **Hind Vadodara** (Indian Type Foundry, OFL, ships
> both scripts) if a warmer humanist face is acceptable. Nothing in the
> console is bilingual today, so this costs nothing yet; it will the moment
> Gujarati labelling is required, and that decision is deferred, not made.

Rejected: Space Grotesk and similar geometric display sans (currently
ubiquitous in generated interfaces); the system font stack (no identity, and
renders differently on the demo machine than on the recording machine);
Archivo (more institutional weight, but no Indic sibling either and heavier
than this console needs).

**Self-host the font files.** The demo and the recording may run on a machine
with no internet. A webfont that fails to load silently reverts the entire
direction to the system stack.

### 5.1 The plate is an object

A vehicle registration number is the single most important string in this
product and is a physical stamped object in the world. Treat it as one, not as
a table cell:

```
┌───────────────────┐
│  GJ 01 AB 1234    │   IBM Plex Mono, uppercase, +0.06em tracking,
└───────────────────┘   raised --ink-700 surface, 1px --ink-600 rule
```

Applied consistently in the Journey search, alert rows, watchlist entries,
recent sightings, and the detector view. An unconfirmed read from the detector
keeps the worker's own `?` suffix and takes the dashed treatment — a plate the
reader is still unsure about must never look like one it has confirmed.

### 5.2 Scale

All sizes in `rem` on a 16px root, landing on the 4px baseline. Tabular figures
(`font-variant-numeric: tabular-nums`) on every number that appears in a column
or updates in place.

```
--fs-display  1.625rem  / 1.15  700, -0.022em   26px  page + view titles   (h1)
--fs-title    1.1875rem / 1.2   700, -0.012em   19px  section headings     (h2)
--fs-section  0.9375rem / 1.25  700              15px  panel/modal headings (h3)
--fs-body     0.875rem  / 1.5   400              14px  prose, h4
--fs-data     0.8125rem / 1.4   Mono, tabular    13px  machine identifiers
--fs-label    0.6875rem / 1.2   600, +0.09em     11px  uppercase eyebrows
```

`rem` rather than `px` throughout, so an operator who has raised their browser
font size gets a console that scales with it.

The jumps are deliberately wide so a level is recognisable on its own rather
than by comparison with its neighbour, and the two large steps carry negative
tracking — type set tight at size reads as a decision, at default spacing it
reads as a default.

> **These are real custom properties, and the headings consume them.** An
> earlier version of this section existed only as a comment in `style.css`:
> nothing was tokenised and nothing consumed it, so every heading picked its
> own value and they all landed between 14 and 16px. `.admin-view h3` was
> 14px — identical to body text. That absence of hierarchy, not the typeface,
> was the substance of "headings lack presence."
>
> Sizes are set on `h1`–`h4` globally; components set only margins. The rule
> deliberately carries **no `text-transform`** — an element selector cannot
> know what a heading contains, and some render dynamic values
> (`TrackOverlayPlayer` renders `<h4>{label}</h4>`), so globally uppercasing
> `h4` would mangle names. The uppercase eyebrow is opt-in via `.eyebrow`.

## 6. Layout, spacing, and depth

### 6.1 Shell

The current header-plus-centred-`1400px`-`<main>` wastes a control-room screen.
Replace with a fixed left rail, a full-bleed work area, and a persistent status
strip.

```
┌────────────┬──────────────────────────────────────────────────────┐
│ SENTINEL   │                                                      │
│            │                                                      │
│ Live       │                                                      │
│ Alerts  ⑶  │                  work area, full bleed               │
│ Journey    │                                                      │
│ Watchlist  │                                                      │
│ Registry   │                                                      │
│ Admin      │                                                      │
│            │                                                      │
│ ─────────  │                                                      │
│ R. Patel   │                                                      │
│ Traffic    │                                                      │
├────────────┴──────────────────────────────────────────────────────┤
│ 24/30 live · 6 workers · 3 open · 5 depts ·           polled 2s ago │
└───────────────────────────────────────────────────────────────────┘
```

The **status strip** carries what is true regardless of view: cameras live over
total, running analytics workers, open alerts, the operator's grant scope, and
time since the last poll. It makes every screenshot and every frame of the
recording self-documenting, and it gives polling a quiet heartbeat so
individual views do not need spinners.

Every figure is one the API actually reports. An earlier draft of this section
showed `6 workers (2 queued)` **against the cap**. The per-camera status endpoint
now reports `queued` and `queue_position`, but the global status endpoint still
returns only started workers and the configured caps are not sent to the
client. The strip therefore cannot honestly show a global queued total or cap.
A console whose whole thesis is making the limits of its own knowledge legible
cannot open by displaying a number it invented. For the same reason the worker
count renders as an em-rule, not `0`, when the status call fails: unknown is
not none.

The poll age reads `AlertsContext`'s existing 4s poll rather than running a
second timer, and is only advanced on a *successful* poll — so when the
backend goes away the age climbs and turns amber, instead of a frozen number
reading as healthy.

### 6.2 Spacing scale

One scale, 4px baseline, no arbitrary values:

```
0.25rem  0.5rem  0.75rem  1rem  1.25rem  1.5rem  2rem  3rem
```

Proximity rule: inner spacing is always tighter than outer. Icon-to-text and
mark-to-label sit at `0.5rem`; panel padding is `1rem`; distinct sections are
separated by `2rem`–`3rem`. Radius is `0.375rem` everywhere except video
surfaces, which take `0.25rem`.

Button padding follows the optical rule — vertical at 50–75% of horizontal,
because ascenders and descenders make vertical space read larger:

```css
/* correct */  padding: 0.5rem 1rem;
/* wrong   */  padding: 1rem 1rem;   /* reads bloated */
```

### 6.3 Depth

Depth signals affordance. It goes on things you can act on, and nowhere else:

| Surface | Treatment |
|---|---|
| Buttons, form controls, plate objects | `--depth-1` |
| Raised cards, focused camera tile, open `<dialog>` | `--depth-2` |
| Panels, table rows, video surfaces, map | flat — one surface step plus a `--ink-600` hairline |

```css
:root {
  --depth-1: inset 0 1px 0 hsl(0 0% 100% / 0.12),
             0 1px 2px hsl(var(--ground-h) 20% 2% / 0.5);
  --depth-2: inset 0 1px 0 hsl(0 0% 100% / 0.16),
             0 4px 8px hsl(var(--ground-h) 20% 2% / 0.55);
}
```

Never a single flat drop-shadow: the inset top edge establishes a light source
and the drop shadow places the element above the ground. Both, always, on
anything raised.

The `frontend-standards` alphas are calibrated for light grounds and need
adapting here. The white inset stays near its stated strength — on a 6%
lightness ground it is doing most of the work — but a `0.1` black drop shadow
is invisible against `--ink-900` and rises to `0.5`.

Table rows and the video wall stay flat deliberately. Depth on a 30-tile grid
turns a data wall into a bevel showroom and competes with the absence textures
in §3.2, which are also non-flat. Affordance gets depth; content does not.

### 6.4 Responsive floor

The rail collapses to a top bar under 900px, the Live grid drops from three
columns to two to one, and every table gets a horizontal scroll container
rather than shrinking its type. The console is a desk product; mobile must
remain usable, not optimal.

## 7. Component rules

### Certainty marks (replaces `Badge.jsx`)

The four badge helpers become one component driven by an epistemic state, not
by ad-hoc colour classes. Texture and label together, per §3.1:

| State | Treatment | Label | Replaces |
|---|---|---|---|
| confirmed | solid 2px left rule in `--ink-600`, `--haze-100` text | *(none — the value speaks)* | `badge-confirmed`, `badge-ok` where it meant certainty |
| inferred | dashed 2px left rule, `--haze-300` text, derivation on hover/focus | `inferred` | `badge-inferred`, `badge-warn` where it meant approximate |
| unknown | solid rule, `—` in place of the value | `not surveyed` | `badge-muted` |
| withheld | 45° hatch in `--ink-600` on `--ink-800`, no value | `withheld` | *(new — no current equivalent)* |

Confirmed is the only unlabelled state, because it is the default and labelling
it would put a word on every row in the table to say nothing. The other three
are always labelled.

Health and status remain coloured, because they are urgency, not epistemics:
`live` in `--nominal`, `reconnecting` and `queued` in `--degraded`, `offline`
and `failed` in `--critical`. A camera can be simultaneously `live` (coloured)
and `inferred` (textured) — that combination is common and must read cleanly.

### Camera tile

Ground `--ink-900`, flat. Overlay bar only on hover, focus, or a non-nominal
state, so a healthy wall shows video and nothing else. Reconnect count and the
`live −Ns` latency estimate keep their current honesty and move to `data-sm`
mono. Non-streaming tiles take their absence-grid texture and word from §3.2.
The focused tile is the one tile that takes `--depth-2`, which is also how
selection is expressed — never a colour.

### Tables

`--ink-800` surface, `--ink-600` row rules, `--ink-700` on hover, flat
throughout. Headers in the `label` style. Every identifier column in mono,
every timestamp tabular. The row-flash on newly polled alerts survives, retuned
to a `--critical` wash at low alpha decaying over 2.5s, and is suppressed under
`prefers-reduced-motion`.

### Map

Dark base tiles so the map is one surface with the console, not a bright window
in it. Markers encode urgency in fill and epistemics in border: a solid border
is a confirmed location, dashed is an approximate geocode. Unplaced cameras keep
their explicit side list and are counted in the header — never dropped.

### Journey timeline

Numbered stops are **kept**, and are the one legitimate use of sequence
numbering in this console: the journey genuinely is an ordered sequence, and the
numbers are the binding between the timeline rows and the route-map markers.
Do not copy the pattern into views where order carries no information.

Between consecutive stops, show the elapsed interval in the connector rather
than leaving a blank gutter. The gap between two sightings is the most
investigatively interesting quantity on the screen and is currently invisible.

### Forms, modals, buttons

Inputs on `--ink-700` with a `--ink-600` rule, `--depth-1`, and a `--haze-100`
focus ring; never remove focus outlines. Primary action is a filled
`--haze-100`-on-`--ink-900` button with `--depth-1` — light on dark, since
colour is not available for interaction. Destructive actions take `--critical`
text on a bordered surface, never a filled red button. Modals are native
`<dialog>` (§8).

### Empty and error states

An empty screen states what would appear there and the one action that fills it.
Errors state what happened and what to do, in the interface's voice, and never
apologise. "No sightings for GJ01AB1234 yet. 6 of 30 cameras can read plates —
review coverage in Registry." not "No data found."

## 8. Native elements

Three replacements, each a net reduction in code and an accessibility gain:

- **`<dialog>`** replaces the div-based `.modal-backdrop` in
  [`Modal.jsx`](frontend-v2/src/components/Modal.jsx). Open with `.showModal()`,
  close with `.close()`, and set `inert` on the shell container while it is open
  so background scroll and screen-reader content are both sealed off. Focus
  trapping, Esc-to-close, and the backdrop come free and currently do not exist
  at all. Used by the create/edit camera and watchlist-entry modals.
- **`<details>`/`<summary>`** for disclosure: the unplaced-cameras panel in the
  Registry map, and the Admin department directory. No JS.
  > The directory needed **restructuring**, not a swap: its expand/collapse was
  > a second `<tr>` toggled by a button, and `<details>` cannot validly wrap
  > table rows. It is now a list of `<details>` cards, and `expandedDepartments`
  > state is gone entirely. Note that `display:flex` on a `<summary>` suppresses
  > the native disclosure marker — it has to be redrawn by hand.
- **`<meter>`** for genuinely metered quantities: per-stop plate-read confidence
  in Journey, and the detector's decode backlog against its queue capacity.
  These are bounded ratios with a known maximum, which is exactly what `<meter>`
  is for, and it carries its value to assistive technology without an ARIA
  dance. Style it to the palette; the semantics are the point.
  > An earlier draft also listed *gap-analysis coverage* and *worker slots
  > against the cap*. Neither is meterable client-side: the gap-analysis report
  > is a server-rendered iframe with no number in the React app, and the worker
  > cap is never sent to the client (see §6.1).

Where form fields are typed, give them `inputmode` (`email` on the sign-in
field, `numeric` on coordinate and threshold inputs) so a tablet in the field
raises the right keyboard.

## 9. Motion

Three permitted uses, all functional:

1. The alert row-flash on arrival (exists; retune).
2. Surface and depth transitions on hover and focus, 120ms.
3. The status strip's poll heartbeat.

Nothing else. No page transitions, no entrance animations, no ambient movement.
On a wall an operator watches for hours, motion means something changed;
decorative motion spends that signal. `prefers-reduced-motion: reduce` disables
1 and 3 and shortens 2 to zero.

## 10. Writing

The console already writes well in places — "Route built from confirmed plate
reads only", "N additional stop(s) are hidden because their departments are
outside your grants". Hold that standard everywhere:

- Name things as the operator understands them, not as the system implements
  them. "Plate reading" over "ANPR worker" in operator-facing copy; the
  technical term is fine in Admin and the detector view, where the audience is
  different.
- An action keeps its name across its whole lifecycle. A button that says
  "Acknowledge" produces a row that says "Acknowledged".
- State what is excluded and why, with a count, wherever the console shows a
  filtered or redacted set.
- Certainty labels are single lowercase words — `inferred`, `withheld`,
  `not surveyed` — and are the same word everywhere they appear.
- Sentence case throughout. Labels in the `label` style are the only uppercase.

## 11. Accessibility floor

Not negotiable, and not announced in the UI: AA contrast on all text and
urgency marks; visible keyboard focus on every interactive element including
camera tiles; every epistemic state legible without colour *and* without
texture, because the word is always present; reduced motion respected; every
colour-carried status also available as text; tables with real headers and
scopes; `inert` on the shell whenever a dialog is open.

## 12. What this direction deliberately does not do

- No light theme. One surface, executed precisely, beats two executed loosely
  eight days before a deadline. This is a considered exception to the
  `prefers-color-scheme` guidance in `frontend-standards`: there is no light
  design to switch to.
- No component library or CSS framework. The console's entire design layer is
  ~760 lines of hand-written CSS across `style.css` and `auth.css` (up from
  ~380 before this direction, roughly half of that growth being comments
  recording *why* a rule is the way it is); a framework would be larger than
  the thing it replaces.
- No routing changes. Markup changes are confined to the shell (§6.1), the
  absence grid (§3.2), the timeline connectors (§7), the certainty component
  (§7), the native-element swaps (§8), and the Admin department directory
  (§8). One deliberate exception to "no state logic changes": `AlertsContext`
  gained a `lastPolledAt` timestamp, because the status strip's poll age has
  to come from the real poll rather than a second timer invented to display it.
- No new dependency except self-hosted font files.

## 13. Adoption

All six steps were implemented on `feat/operator-console-redesign`, one commit
per step, and merged to `main` in `36ffb42`, in this order:

| # | Step | Commit |
|---|---|---|
| 1 | **Tokens and type** — HSL ramp, `rem` scale, depth tokens, self-hosted IBM Plex, favicon, per-view tab titles | `04052d0` |
| 2 | **Certainty component** — replaces `Badge.jsx`, resolves §2's amber collision | `eb9a265` |
| 3 | **Native elements** — `<dialog>` + `inert`, `<details>`, `<meter>` | `8a37eed` |
| 3b | **Department directory** restructured to `<details>` cards | `0c68310` |
| 4 | **Map** — dark tiles and Leaflet chrome (tables/forms/buttons landed in 1–2) | `c8c5a9b` |
| 5 | **Shell** — left rail, full-bleed work area, status strip | `fb114fb` |
| 6 | **Absence grid and timeline connectors** | `25bf7e5` |

Two fix commits sit between them: `1d77de1` (four bugs found clicking through
the running app — a white-on-white CSV control that had never matched its own
CSS rule, a Leaflet map mis-measuring itself inside the new `<dialog>`, a
checkbox stretched by the text-input rule, and buttons with no `:disabled`
styling at all) and `7f5c3d6` (light surfaces were getting a white top-inset
highlight that is invisible on a near-white fill, so `.primary` alone read as
flat).

Steps 1–4 were a retheme and carried little regression risk. Steps 5–6 changed
layout and need the demo re-verified.

**Still required before this is citable as checkpoint evidence:** redacted
browser evidence under `artifacts/`, captured against the authenticated app —
every section here was verified against static harnesses built from the real
compiled CSS, because the implementing environment had no credentials.
A teammate clean-clone review is also outstanding. `PROJECT_STATE.md` remains
the authority on what exists.

### Not done, and why

| Item | Blocker |
|---|---|
| `withheld` certainty state (§3.1) | No per-field redaction signal in the API |
| `outside your grants` tile (§3.2) | `GET /api/cameras` filters those rows out entirely |
| Global queued-worker count and configured cap (§6.1) | Per-camera status now reports `queued` and `queue_position`, but the API does not expose a global queued total or configured cap |
| Gap-analysis coverage `<meter>` (§8) | Server-rendered iframe; no client-side number |

The first two point at the same backend gap: **the API tells the console what it
may see, but never how much it is not seeing.** Adding hidden counts the way
`/journey` already reports `restricted_stops` would unlock both. It is a useful
scope-awareness enhancement, but the mandatory read/denial audit gaps take
priority under `GOV-NFR-003`; current role/grant verification is recorded in
`artifacts/public/checkpoint-c3/rbac-smoke-2026-08-31.md`.

## 14. Standards conformance

This document follows the `frontend-standards` skill except where noted:

| Rule | Status |
|---|---|
| HSL over hex/RGB | Followed — §4, neutral ramp generated from two variables |
| 4-colour rotation formula | **Partial, deliberate.** Applied to the neutral ramp; not to the urgency hues, because red-means-danger is a convention a formula would break. §4 states the reasoning and notes where rotation and semantics happen to agree. |
| Dual-shadow depth | Followed on interactive surfaces (§6.3), with alphas adapted for a dark ground. Content surfaces stay flat by design. In implementation this needed a second token, `--depth-1-light`: the skill's inset *white* top highlight is invisible on a near-white fill, so light surfaces take a dark **bottom** inset instead — same "light from above" cue, opposite end of the lightness ramp. |
| `rem` on a 4px baseline | Followed — §5.2, §6.2 |
| Optical button padding | Followed — §6.2 |
| Conventions over novelty | **Partial, deliberate.** The certainty textures are novel, so every one of them is paired with a plain word (§3.1) and none requires a legend. The novelty is a second, faster channel over a conventional one — not a replacement for it. `withheld` has no convention to use because no comparable product shows redaction at all. |
| Shortest path to the goal | Followed — §6.1 puts grant scope, alert count, and system health permanently on screen rather than behind navigation |
| Native HTML over JS | Followed — §8. `<dialog>` removed a hand-rolled backdrop and added focus trapping the old version never had; `<details>` deleted the `expandedDepartments` state outright. |
| `prefers-color-scheme` dark mode | **Not applicable, deliberate.** Single dark theme; see §12. |
