import { useEffect, useRef } from "react";

const TAU = Math.PI * 2;

export default function SurveillanceGlobe() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let t = 0;
    let pointerX = 0;
    let pointerY = 0;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let hover = false;
    let rotation = -0.35;
    let pitch = -0.08;
    const basePitch = -0.08;

    const resize = () => {
      const box = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(320, box.width);
      height = Math.max(320, box.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const stars = Array.from({ length: 110 }, (_, i) => ({
      a: (i * 2.399) % TAU,
      r: 0.25 + ((i * 37) % 100) / 100,
      z: ((i * 17) % 100) / 100,
    }));

    // Kept from the original globe: these are the same stylised urban routes,
    // now wrapped onto a spherical surface so the globe genuinely rotates in 3D.
    const roads = [
      [[-0.92, 0.34], [-0.42, 0.08], [0.05, -0.06], [0.62, -0.3], [0.92, -0.5]],
      [[-0.82, -0.4], [-0.38, -0.22], [0.06, 0.02], [0.42, 0.38], [0.83, 0.56]],
      [[-0.55, -0.86], [-0.24, -0.44], [0.02, 0], [0.2, 0.48], [0.43, 0.86]],
      [[-0.9, 0.0], [-0.46, 0.02], [0, 0.0], [0.48, 0.0], [0.9, 0.0]],
    ];

    // Map the old 2D route coordinates onto longitude/latitude.
    const roadPoint = ([x, y]) => ({
      lon: x * Math.PI,
      lat: y * (Math.PI / 2) * 0.92,
    });
    const road3d = roads.map((road) => road.map(roadPoint));

    const cityNodes = [
      [-0.68, 0.18], [-0.25, -0.12], [0.05, -0.02], [0.46, -0.28],
      [0.72, 0.44], [-0.46, -0.5], [0.2, 0.42],
    ].map(([x, y]) => roadPoint([x, y]));

    const spherePoint = (lon, lat) => {
      const cl = Math.cos(lat);
      return { x: cl * Math.sin(lon), y: Math.sin(lat), z: cl * Math.cos(lon) };
    };

    const rotatePoint = (p) => {
      const cy = Math.cos(rotation), sy = Math.sin(rotation);
      let x = p.x * cy + p.z * sy;
      let z = -p.x * sy + p.z * cy;
      const cp = Math.cos(pitch), sp = Math.sin(pitch);
      const y = p.y * cp - z * sp;
      z = p.y * sp + z * cp;
      return { x, y, z };
    };

    const project = (p, cx, cy, R) => {
      // Perspective makes the front of the sphere larger and the rear smaller.
      const camera = 3.25;
      const scale = camera / (camera - p.z);
      return { x: cx + p.x * R * scale, y: cy - p.y * R * scale, z: p.z, scale };
    };

    const drawCurve = (points, cx, cy, R, color, lineWidth) => {
      let previous = null;
      ctx.lineWidth = lineWidth;
      ctx.strokeStyle = color;
      ctx.lineCap = "round";
      ctx.beginPath();
      points.forEach((point, i) => {
        const p = rotatePoint(spherePoint(point.lon, point.lat));
        const q = project(p, cx, cy, R);
        // Break at the silhouette so rear-side roads don't draw across the globe.
        if (p.z < -0.02 || !previous) {
          previous = p.z >= -0.02 ? q : null;
          if (previous) ctx.moveTo(q.x, q.y);
        } else {
          ctx.lineTo(q.x, q.y);
          previous = q;
        }
        if (i === points.length - 1 && previous) ctx.stroke();
      });
    };

    const onPointerEnter = (event) => {
      hover = true;
      const rect = canvas.getBoundingClientRect();
      pointerX = event.clientX - rect.left - rect.width / 2;
      pointerY = event.clientY - rect.top - rect.height / 2;
    };
    const onPointerMove = (event) => {
      if (!hover) return;
      const rect = canvas.getBoundingClientRect();
      pointerX = event.clientX - rect.left - rect.width / 2;
      pointerY = event.clientY - rect.top - rect.height / 2;
    };
    const onPointerLeave = () => {
      hover = false;
      pointerX = 0;
      pointerY = 0;
    };

    const draw = () => {
      // Nothing moves by itself. Hover position is the only motion input.
      // Horizontal cursor position controls the 3D Y rotation direction/speed;
      // vertical position adds a small pitch so the sphere follows the cursor.
      if (hover && !reduced) {
        const maxX = Math.max(1, width * 0.34);
        const maxY = Math.max(1, height * 0.34);
        const nx = Math.max(-1, Math.min(1, pointerX / maxX));
        const ny = Math.max(-1, Math.min(1, pointerY / maxY));
        rotation += nx * 0.022;
        pitch += (basePitch + ny * 0.16 - pitch) * 0.08;
        t += 0.008;
      }

      const light = document.documentElement.getAttribute("data-theme") === "light";
      const css = getComputedStyle(document.documentElement);
      const entityHex = css.getPropertyValue("--entity-hex").trim() || "#2f8fff";
      const brightHex = css.getPropertyValue("--entity-bright-hex").trim() || entityHex;
      const hexToRgba = (hex, a) => {
        const h = hex.replace("#", "");
        const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
        const n = parseInt(full, 16);
        if (!Number.isFinite(n)) return `rgba(47, 143, 255, ${a})`;
        const r = (n >> 16) & 255;
        const g = (n >> 8) & 255;
        const b = n & 255;
        return `rgba(${r}, ${g}, ${b}, ${a})`;
      };
      const palette = light ? {
        glowA: hexToRgba(entityHex, 0.2), glowB: hexToRgba(entityHex, 0.08),
        /* slightly stronger accent wash in light mode */
        globe0: hexToRgba(entityHex, 0.42),
        globe1: hexToRgba(entityHex, 0.2),
        globe2: hexToRgba(entityHex, 0.1),
        grid: hexToRgba(entityHex, 0.28), road: [hexToRgba(entityHex, 0.6), hexToRgba(entityHex, 0.35)],
        packet: [brightHex, entityHex], scan: hexToRgba(entityHex, 0.72), ring: hexToRgba(entityHex, 0.35), cross: hexToRgba(entityHex, 0.48),
      } : {
        glowA: hexToRgba(entityHex, 0.16), glowB: hexToRgba(brightHex, 0.05),
        globe0: hexToRgba(entityHex, 0.25), globe1: "rgba(8, 31, 65, .72)", globe2: "rgba(2, 7, 18, .95)",
        grid: hexToRgba(brightHex, 0.15), road: [hexToRgba(brightHex, 0.52), hexToRgba(entityHex, 0.22)],
        packet: [brightHex, entityHex], scan: hexToRgba(brightHex, 0.8), ring: hexToRgba(brightHex, 0.2), cross: hexToRgba(brightHex, 0.5),
      };

      ctx.clearRect(0, 0, width, height);
      const cx = width * 0.5;
      const cy = height * 0.5;
      const R = Math.min(width, height) * 0.34;

      const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.55);
      bg.addColorStop(0, palette.glowA); bg.addColorStop(0.5, palette.glowB); bg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = bg; ctx.fillRect(0, 0, width, height);

      stars.forEach((s) => {
        const a = s.a + t * (0.18 + s.z * 0.12);
        const x = cx + Math.cos(a) * R * (1.12 + s.r * 0.42);
        const y = cy + Math.sin(a) * R * (0.68 + s.r * 0.32);
        ctx.fillStyle = hexToRgba(brightHex, 0.18 + 0.5 * (0.5 + 0.5 * Math.sin(a * 3 + t)));
        ctx.beginPath(); ctx.arc(x, y, 1 + s.z * 1.3, 0, TAU); ctx.fill();
      });

      // Sphere body + soft edge highlight.
      const globe = ctx.createRadialGradient(cx - R * 0.30, cy - R * 0.36, R * 0.06, cx, cy, R * 1.04);
      globe.addColorStop(0, palette.globe0); globe.addColorStop(0.55, palette.globe1); globe.addColorStop(1, palette.globe2);
      ctx.fillStyle = globe; ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.fill();

      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.clip();

      // True spherical latitude/longitude grid.
      for (let lat = -75; lat <= 75; lat += 15) {
        let first = true;
        ctx.beginPath();
        for (let lon = -180; lon <= 180; lon += 4) {
          const p3 = rotatePoint(spherePoint(lon * Math.PI / 180, lat * Math.PI / 180));
          if (p3.z < -0.05) { first = true; continue; }
          const q = project(p3, cx, cy, R);
          if (first) { ctx.moveTo(q.x, q.y); first = false; } else ctx.lineTo(q.x, q.y);
        }
        ctx.strokeStyle = palette.grid; ctx.lineWidth = 0.7; ctx.stroke();
      }
      for (let lon = -165; lon <= 180; lon += 15) {
        let first = true;
        ctx.beginPath();
        for (let lat = -90; lat <= 90; lat += 4) {
          const p3 = rotatePoint(spherePoint(lon * Math.PI / 180, lat * Math.PI / 180));
          if (p3.z < -0.05) { first = true; continue; }
          const q = project(p3, cx, cy, R);
          if (first) { ctx.moveTo(q.x, q.y); first = false; } else ctx.lineTo(q.x, q.y);
        }
        ctx.strokeStyle = palette.grid; ctx.lineWidth = 0.7; ctx.stroke();
      }

      // Same original road network, but now genuinely wrapped around the sphere.
      road3d.forEach((road, index) => drawCurve(road, cx, cy, R, palette.road[index === 0 ? 0 : 1], index === 0 ? 2.2 : 1.1));

      // City nodes + traffic packets follow the spherical surface.
      cityNodes.forEach((node, i) => {
        const p3 = rotatePoint(spherePoint(node.lon, node.lat));
        if (p3.z < -0.02) return;
        const q = project(p3, cx, cy, R);
        const pulse = 1 + Math.sin(t * 4 + i) * 0.25;
        ctx.fillStyle = palette.packet[i % 2]; ctx.shadowBlur = 10; ctx.shadowColor = ctx.fillStyle;
        ctx.beginPath(); ctx.arc(q.x, q.y, (2 + (p3.z + 1) * 1.2) * pulse, 0, TAU); ctx.fill();
      });
      ctx.shadowBlur = 0;

      for (let i = 0; i < 12; i += 1) {
        const p = (t * (0.12 + i * 0.008) + i / 12) % 1;
        const roadIndex = i % road3d.length;
        const route = road3d[roadIndex];
        const seg = Math.min(route.length - 2, Math.floor(p * (route.length - 1)));
        const f = p * (route.length - 1) - seg;
        const a = route[seg], b = route[seg + 1];
        const lon = a.lon + (b.lon - a.lon) * f;
        const lat = a.lat + (b.lat - a.lat) * f;
        const p3 = rotatePoint(spherePoint(lon, lat));
        if (p3.z < -0.01) continue;
        const q = project(p3, cx, cy, R);
        ctx.fillStyle = i % 4 === 0 ? palette.packet[0] : palette.packet[1];
        ctx.shadowBlur = 10; ctx.shadowColor = ctx.fillStyle;
        ctx.beginPath(); ctx.arc(q.x, q.y, 2.1 * q.scale, 0, TAU); ctx.fill();
      }
      ctx.shadowBlur = 0;
      ctx.restore();

      // 3D sphere rim, scan ring and original targeting treatment.
      ctx.strokeStyle = palette.ring; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.stroke();
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(-t * 0.7); ctx.strokeStyle = palette.scan; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(0, 0, R * 1.1, -0.2, 0.65); ctx.stroke(); ctx.restore();

      ctx.strokeStyle = palette.ring; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, R * 1.17, 0, TAU); ctx.stroke();
      ctx.strokeStyle = palette.cross; ctx.setLineDash([5, 7]); ctx.beginPath();
      ctx.moveTo(cx - R * 1.27, cy); ctx.lineTo(cx + R * 1.27, cy); ctx.moveTo(cx, cy - R * 1.27); ctx.lineTo(cx, cy + R * 1.27); ctx.stroke(); ctx.setLineDash([]);

      if (!reduced) raf = requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize);
    canvas.addEventListener("pointerenter", onPointerEnter);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerleave", onPointerLeave);
    draw();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("pointerenter", onPointerEnter);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerleave", onPointerLeave);
    };
  }, []);

  return <canvas ref={ref} className="surveillance-globe" aria-hidden="true" />;
}
