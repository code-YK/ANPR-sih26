import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import {
  ArrowRight,
  Bell,
  Camera,
  Car,
  Crosshair,
  Fingerprint,
  MapPinned,
  Moon,
  Palette,
  Navigation,
  Radar,
  Route,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Sun,
  Video,
} from "lucide-react";

import BrandMark from "../../components/BrandMark.jsx";
import LandingMap from "./LandingMap.jsx";
import SurveillanceGlobe from "./SurveillanceGlobe.jsx";
import { useTheme } from "../../context/ThemeContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

gsap.registerPlugin(ScrollTrigger);

const CAPABILITIES = [
  { icon: Video, title: "Live camera mesh", body: "See feeds, detector state, plate reads and camera health as one city-wide operational surface." },
  { icon: Radar, title: "ANPR intelligence", body: "Turn moving vehicles into searchable identities with time, location and confidence attached." },
  { icon: Route, title: "Trajectory reconstruction", body: "Connect sightings across the road graph to reconstruct where a vehicle travelled and when." },
  { icon: MapPinned, title: "Geospatial command", body: "Layer cameras, roads, incidents and movement onto a live map built for the control room." },
  { icon: ShieldCheck, title: "Watchlist response", body: "Surface priority matches instantly with accountable workflows and operator audit trails." },
  { icon: Fingerprint, title: "Evidence intelligence", body: "Search plates and recordings, inspect detections and preserve structured investigative context." },
];

/* Keep plates on the right half so they never collide with hero copy */
const FLOAT_PLATES = [
  { plate: "DL 01 CX 8820", x: "12%", y: "8%", delay: "0s" },
  { plate: "MH 12 AB 4291", x: "48%", y: "28%", delay: "1.1s" },
  { plate: "KA 05 MN 1134", x: "8%", y: "52%", delay: "0.55s" },
  { plate: "TN 09 BK 7702", x: "40%", y: "74%", delay: "1.7s" },
];

function ThemeToggleCompact() {
  const { theme, toggleTheme } = useTheme();
  const isLight = theme === "light";
  return (
    <button
      type="button"
      className="secondary theme-toggle landing-theme-toggle"
      onClick={toggleTheme}
      title={isLight ? "Switch to dark mode" : "Switch to light mode"}
      aria-label={isLight ? "Switch to dark mode" : "Switch to light mode"}
    >
      {isLight ? <Moon size={16} strokeWidth={2} /> : <Sun size={16} strokeWidth={2} />}
    </button>
  );
}

function ColorSwitchCompact() {
  const { accent, setAccent, accents } = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const current = accents.find((c) => c.id === accent) ?? accents[0];

  useEffect(() => {
    if (!open) return undefined;
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    // capture phase so we still receive the event even if something stops bubble
    document.addEventListener("pointerdown", onDoc, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function pickColor(e, id) {
    e.preventDefault();
    e.stopPropagation();
    setAccent(id);
    setOpen(false);
  }

  return (
    <div className="color-switch landing-color-switch" ref={rootRef}>
      <button
        type="button"
        className="secondary theme-toggle landing-theme-toggle color-switch-btn"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        title={`Theme color: ${current.label}`}
        aria-label={`Theme color: ${current.label}. Open color switch`}
        aria-expanded={open}
      >
        <span
          className="color-switch-swatch"
          style={{ background: `hsl(${current.hue} ${current.sat}% 50%)` }}
          aria-hidden="true"
        />
        <Palette size={15} strokeWidth={2} />
      </button>
      {open && (
        <div
          className="color-switch-menu landing-color-menu"
          role="listbox"
          aria-label="Theme colors"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {accents.map((c) => (
            <button
              key={c.id}
              type="button"
              role="option"
              aria-selected={c.id === accent}
              className={c.id === accent ? "color-switch-option is-active" : "color-switch-option"}
              onPointerDown={(e) => pickColor(e, c.id)}
              onClick={(e) => pickColor(e, c.id)}
              title={c.label}
            >
              <span
                className="color-switch-swatch"
                style={{ background: `hsl(${c.hue} ${c.sat}% 50%)` }}
                aria-hidden="true"
              />
              <span>{c.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LandingView() {
  usePageTitle("Home");
  const rootRef = useRef(null);
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const ctx = gsap.context(() => {
      if (reduced) return;

      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.from(".landing-header", { y: -18, opacity: 0, duration: 0.5 })
        .from(".lp-hero-copy > *", { y: 24, opacity: 0, stagger: 0.07, duration: 0.45 }, "-=0.2")
        .from(".landing-hero-stage", { opacity: 0, scale: 0.96, duration: 0.7 }, "-=0.45")
        .from(".landing-float-plate", { y: 16, opacity: 0, stagger: 0.08, duration: 0.4 }, "-=0.35")
        .from(".landing-orbit-item", { scale: 0.8, opacity: 0, stagger: 0.06, duration: 0.35 }, "-=0.3");

      gsap.to(".landing-float-layer", {
        opacity: 0,
        ease: "none",
        scrollTrigger: {
          trigger: root,
          start: "top top",
          end: "+=380",
          scrub: true,
        },
      });

      gsap.to(".landing-orbit", {
        rotate: 360,
        duration: 80,
        repeat: -1,
        ease: "none",
      });
      gsap.to(".landing-orbit-reverse", {
        rotate: -360,
        duration: 110,
        repeat: -1,
        ease: "none",
      });

      gsap.from(".landing-stat", {
        scrollTrigger: { trigger: ".landing-stats", start: "top 88%" },
        y: 28, opacity: 0, stagger: 0.1, duration: 0.5,
      });
      gsap.from(".landing-card", {
        scrollTrigger: { trigger: ".landing-grid", start: "top 88%" },
        y: 32, opacity: 0, stagger: 0.08, duration: 0.5,
      });
      gsap.from(".landing-access-card", {
        scrollTrigger: { trigger: ".landing-access", start: "top 85%" },
        y: 28, opacity: 0, duration: 0.55,
      });
    }, root);

    return () => ctx.revert();
  }, []);

  return (
    <div className="landing landing-cinematic" ref={rootRef}>
      {/* Live city map — Mapbox (VITE_MAPBOX_TOKEN) */}
      <div className="landing-map-layer" aria-hidden="true">
        <LandingMap />
        <div className="landing-map-veil" />
        <div className="landing-map-grid" />
        <div className="landing-map-scan" />
      </div>

      {/* Floating plate chips */}
      <div className="landing-float-layer" aria-hidden="true">
        {FLOAT_PLATES.map((item) => (
          <div
            key={item.plate}
            className="landing-float-plate"
            style={{ left: item.x, top: item.y, animationDelay: item.delay }}
          >
            <span className="landing-float-plate-tag">READ</span>
            <span className="landing-float-plate-num">{item.plate}</span>
          </div>
        ))}
      </div>

      <header className="landing-header">
        <div className="landing-header-inner">
          <div className="landing-brand">
            <BrandMark size={34} />
            <span>
              CityTraceAI
              <span className="sub">Urban ANPR platform</span>
            </span>
          </div>
          <div className="landing-header-actions">
            <ThemeToggleCompact />
            <ColorSwitchCompact />
            <Link to="/login" className="secondary landing-link-btn">Sign in</Link>
            <Link to="/login?mode=register" className="primary landing-link-btn">Request access</Link>
          </div>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-copy lp-hero-copy">
            <p className="landing-eyebrow">
              <Radar size={14} strokeWidth={2} aria-hidden="true" />
              City-scale ANPR · Command ready
            </p>
            <h1>
              The city leaves a trail.
              <span className="landing-title-accent"> We read every plate.</span>
            </h1>
            <p className="landing-lead">
              CityTraceAI fuses live cameras, road networks, and watchlist intelligence into one
              operator console — built for police control rooms that need clarity under pressure.
            </p>
            <div className="landing-cta">
              <Link to="/login" className="primary landing-link-btn landing-cta-primary">
                Enter console
                <ArrowRight size={16} strokeWidth={2.25} aria-hidden="true" />
              </Link>
              <Link to="/login?mode=register" className="secondary landing-link-btn">
                Request department access
              </Link>
            </div>
            <ul className="landing-trust">
              <li>Role-based access</li>
              <li>Audit-friendly trails</li>
              <li>Map-linked journeys</li>
              <li>24×7 duty desk</li>
            </ul>
          </div>

          <div className="landing-hero-stage landing-command-stage">
            <div className="command-stage-grid" aria-hidden="true" />
            <div className="command-stage-beam command-stage-beam-a" aria-hidden="true" />
            <div className="command-stage-beam command-stage-beam-b" aria-hidden="true" />
            <div className="command-stage-corner command-stage-corner-tl">CAM / 047 · ONLINE</div>
            <div className="command-stage-corner command-stage-corner-tr">LAT 28.6139 · LON 77.2090</div>
            <div className="command-stage-corner command-stage-corner-bl">PLATE LOCK · 98.7%</div>
            <div className="command-stage-corner command-stage-corner-br">UPLINK · ENCRYPTED</div>

            <div className="landing-orbit landing-orbit-reverse" aria-hidden="true">
              <span className="landing-orbit-item" style={{ "--i": 0 }}><Camera size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 1 }}><Car size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 2 }}><MapPinned size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 3 }}><Shield size={14} /></span>
            </div>
            <div className="landing-orbit" aria-hidden="true">
              <span className="landing-orbit-item" style={{ "--i": 0 }}><Crosshair size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 1 }}><Navigation size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 2 }}><Fingerprint size={14} /></span>
              <span className="landing-orbit-item" style={{ "--i": 3 }}><Sparkles size={14} /></span>
            </div>

            <div className="surveillance-core">
              <SurveillanceGlobe />
              <div className="surveillance-core-label">
                <span className="landing-status-dot" />
                CITY GRID // LIVE
              </div>
              <div className="surveillance-core-readout">
                <strong>4,281</strong>
                <span>CAMERAS</span>
              </div>
            </div>

            <div className="command-card command-card-camera">
              <span className="command-card-icon"><Camera size={15} /></span>
              <div><small>LIVE FEED</small><strong>CAM-047 / RING RD</strong></div>
              <i className="command-live-dot" />
            </div>
            <div className="command-card command-card-plate">
              <span className="command-card-icon"><Car size={15} /></span>
              <div><small>ANPR MATCH</small><strong>DL 01 CX 8820</strong></div>
              <span className="command-confidence">98.7%</span>
            </div>
            <div className="command-card command-card-route">
              <span className="command-card-icon"><Route size={15} /></span>
              <div><small>TRAJECTORY</small><strong>12 NODES · 18.4 KM</strong></div>
            </div>
          </div>
        </section>

        <section className="landing-stats" aria-label="Platform pillars">
          <div className="landing-stat">
            <div className="landing-stat-icon"><Radar size={18} strokeWidth={2} /></div>
            <strong>Earth to edge</strong>
            <span>From road geometry to camera endpoints — one operational picture.</span>
          </div>
          <div className="landing-stat">
            <div className="landing-stat-icon"><Navigation size={18} strokeWidth={2} /></div>
            <strong>Traffic as signal</strong>
            <span>Plate reads become journeys across the city graph in real time.</span>
          </div>
          <div className="landing-stat">
            <div className="landing-stat-icon"><Fingerprint size={18} strokeWidth={2} /></div>
            <strong>Cyber discipline</strong>
            <span>Clearance, audit trails, and operator accountability by design.</span>
          </div>
        </section>

        <section className="landing-capabilities" aria-labelledby="capabilities-heading">
          <div className="landing-section-head">
            <p className="landing-eyebrow">Capability matrix</p>
            <h2 id="capabilities-heading">Command tools for the ops floor</h2>
            <p>
              Cameras, maps, plates, and people — wired into workflows stakeholders can brief
              without leaving the console.
            </p>
          </div>
          <div className="landing-grid">
            {CAPABILITIES.map(({ icon: Icon, title, body }) => (
              <article key={title} className="landing-card">
                <div className="landing-card-icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={2} />
                </div>
                <h3>{title}</h3>
                <p>{body}</p>
                <div className="landing-card-glow" aria-hidden="true" />
              </article>
            ))}
          </div>
        </section>

        <section className="landing-access" aria-labelledby="access-heading">
          <div className="landing-access-card">
            <div className="landing-access-copy">
              <p className="landing-eyebrow">Secure entry</p>
              <h2 id="access-heading">Authorised operators only</h2>
              <p>
                Accounts are provisioned by department administrators. Sign in with approved
                credentials, or submit a registration request for review.
              </p>
              <div className="landing-cta">
                <Link to="/login" className="primary landing-link-btn">
                  Sign in <ArrowRight size={15} strokeWidth={2.25} aria-hidden="true" />
                </Link>
                <Link to="/login?mode=register" className="secondary landing-link-btn">
                  Request access
                </Link>
              </div>
            </div>
            <div className="landing-access-visual" aria-hidden="true">
              <div className="landing-access-shield">
                <BrandMark size={40} />
                <span>Clearance required</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <div className="landing-brand landing-brand-footer">
            <BrandMark size={24} />
            <span>
              CityTraceAI
              <span className="sub">Operator Console</span>
            </span>
          </div>
          <p>
            Restricted system for authorised law-enforcement and government operators.
            Misuse may be subject to departmental and legal action.
          </p>
        </div>
      </footer>
    </div>
  );
}
