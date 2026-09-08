# Frontend v3 — Operator Console Reskin

Status: Implemented  
Parent: [architecture.md](architecture.md)

## Overview

`frontend-v3` is a full visual reskin of the Sentinel operator console (`frontend-v2`), applying a cinematic dark theme inspired by the Razorpay Buildathon aesthetic. It shares the same React component structure, routing, and API contracts as v2 — only the design language, typography, and interaction layer differ.

## Motivation

The Phase 1 operator console (v2) uses a utilitarian cool-gray palette optimised for legibility. For the hackathon demo and presentation, a more premium, cinematic look was needed — one that conveys the scale and seriousness of the surveillance platform while still meeting all operator UX requirements.

## Design Language

### Color System

A warm near-black ink palette with parchment text hierarchy and gold accent:

| Role | Token | Value |
|------|-------|-------|
| Background | `--ink-900` | `hsl(220 30% 4%)` |
| Panel surface | `--ink-800` | `hsl(220 24% 7%)` |
| Elevated surface | `--ink-700` | `hsl(220 20% 11%)` |
| Border | `--ink-600` | `hsl(220 16% 18%)` |
| Muted text | `--haze-400` | `hsl(35 10% 50%)` |
| Secondary text | `--haze-300` | `hsl(35 18% 72%)` |
| Primary text | `--haze-100` | `hsl(35 40% 92%)` |
| Gold accent | `--entity` | `hsl(35 70% 60%)` |
| Active gold | `--entity-bright` | `hsl(35 80% 72%)` |

Status colours remain semantic: green (nominal), amber (degraded), red (critical).

### Typography

- **Display / body**: Inter (400-900 weights) replacing Instrument Sans
- **Data / monospace**: IBM Plex Mono (400-500 weights) retained
- Tight letter-spacing on display text (`-0.03em`), relaxed on labels (`0.1em`)

### Shape Language

Sharp border-radius throughout (3-4px), contrasting with rounded/pill shapes. Matches the Buildathon's precise, editorial aesthetic.

- `--radius: 4px` — panels, cards, modals
- `--radius-control: 3px` — buttons, inputs, badges
- `--radius-video: 3px` — camera tiles, video players

### Film Grain Overlay

SVG fractal noise texture on `body::after` at 3.5% opacity with a `grainJitter` keyframe animation (0.7s, stepped). Creates an analog/cinematic depth without interfering with readability.

## Animation System

### GSAP Stagger Reveals

Custom `useGsapReveal` hook (`src/hooks/useGsapReveal.js`) applies staggered fade-up + scale entrance animations to grid children.

Used in:
- **Live view** camera grid/strip (35ms stagger, 0.45s duration)
- **Investigate** results grid (50ms stagger)
- **Alerts** table rows (30ms stagger)
- **Watchlist** table rows (30ms stagger)
- **Admin** user cards (60ms stagger)

### CSS Micro-Interactions

| Element | Hover | Press |
|---------|-------|-------|
| Camera tiles | `scale(1.02)` + gold glow | `scale(0.98)` |
| Result cards | `translateY(-2px) scale(1.01)` + gold glow | — |
| Primary buttons | `translateY(-1px)` + gold glow | `scale(0.97)` |
| Secondary buttons | gold border glow | `scale(0.97)` |
| Department cards | `translateY(-1px)` + gold glow | — |

### Glow Effects

Gold accent glow (`box-shadow: 0 0 20px hsl(35 70% 60% / 0.2)`) applied on hover to interactive elements. Pulsing glow animations on status indicators (alert badges, running dots, nav count badges).

### Entrance Animations

Modals, toasts, focused players, and the logs panel all use CSS `@keyframes` entrance animations with the Buildathon's custom easing: `cubic-bezier(0.3, 0, 0.2, 1)`.

### Loading Screen

`LoadingScreen.jsx` replaces the plain "Loading Sentinel..." text with a gold pulsing orb and rotating contextual messages:
- "Warming up the surveillance grid..."
- "Syncing with regional cameras..."
- "Establishing encrypted channels..."
- "Loading operator workspace..."
- "Calibrating detection models..."
- "Almost there, commander..."

### Accessibility

All animations and transitions respect `prefers-reduced-motion: reduce` via a global media query that sets durations to near-zero and removes hover transforms.

## Directory Structure

```
frontend-v3/
  package.json          # independent npm setup (gsap, @fontsource/inter, etc.)
  vite.config.js        # standard Vite + React config
  src/
    main.jsx            # Inter font imports, app bootstrap
    style.css           # complete design token system + all component styles
    auth.css             # auth and admin view styles
    hooks/
      useGsapReveal.js  # GSAP stagger reveal + single-element fade-in hooks
    components/
      LoadingScreen.jsx # cinematic loading with rotating messages
      SentinelMark.jsx  # SVG mark using CSS custom properties
    views/              # same structure as frontend-v2
```

## Dependencies (additions over v2)

| Package | Purpose |
|---------|---------|
| `gsap` | staggered entrance animations, micro-interactions |
| `@fontsource/inter` | primary typeface (replacing `@fontsource/instrument-sans`) |

## Running

```bash
cd frontend-v3
npm install
npm run dev -- --port 5175
```

Or via `.claude/launch.json`:
```json
{
  "name": "frontend-v3",
  "runtimeExecutable": "npm",
  "runtimeArgs": ["--prefix", "frontend-v3", "run", "dev", "--", "--host", "--port", "5175"],
  "port": 5175
}
```
