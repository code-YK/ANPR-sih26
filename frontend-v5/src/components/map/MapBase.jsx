import "leaflet/dist/leaflet.css";
import "./map.css";

import L from "leaflet";
import { TileLayer } from "react-leaflet";

export const DEFAULT_CENTER = [22.6, 71.6];

export function DarkTileLayer() {
  return (
    <TileLayer
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      className="sentinel-dark-tiles"
    />
  );
}

// Cached: react-leaflet replaces a marker's DOM whenever its icon object
// changes identity, so a fresh icon per render rebuilt every marker on every
// hover and poll.
const numberedIcons = new Map();

export function numberedIcon(n, active) {
  const key = `${n}:${active ? 1 : 0}`;
  let icon = numberedIcons.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "",
      html: `<div class="sentinel-route-marker" data-active="${active ? "true" : "false"}">${n}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14],
    });
    numberedIcons.set(key, icon);
  }
  return icon;
}

// A div icon rather than Leaflet's default image marker, whose asset URLs
// don't survive bundling.
export const pinIcon = L.divIcon({
  className: "",
  html: '<div class="sentinel-pin"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 22],
});

/** Map colours are drawn outside the CSS cascade, so they're literal here. */
export const MAP_COLORS = {
  live: "#5fd39a",
  critical: "#f06a5b",
  unknown: "#7d8784",
  signal: "#6d8ff5",
};
