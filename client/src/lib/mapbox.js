import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

import { useTheme } from "../context/ThemeContext.jsx";

export function getMapboxToken() {
  return import.meta.env.VITE_MAPBOX_TOKEN || "";
}

export function mapboxStyleUrl(isLight) {
  return isLight
    ? "mapbox://styles/mapbox/streets-v12"
    : "mapbox://styles/mapbox/navigation-night-v1";
}

export function ensureMapboxToken() {
  const token = getMapboxToken();
  if (token) mapboxgl.accessToken = token;
  return Boolean(token);
}

export { mapboxgl, useTheme };
