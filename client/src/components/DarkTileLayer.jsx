import { TileLayer } from "react-leaflet";
import { useTheme } from "../context/ThemeContext.jsx";

// A dark basemap without depending on a third-party dark-tile service:
// tried CARTO's free dark_all endpoint first (the standard no-signup choice
// for this), and it turned out to no longer serve tiles anonymously --
// every tile came back stamped "API KEY REQUIRED", confirmed live before
// this shipped. Standard OSM tiles (the same source the app already used)
// plus a CSS filter on the tile pane instead: reliable, no new external
// dependency or quota risk, and it's the well-known technique for exactly
// this situation. Colour-tuned by eye against a live render, not just the
// generic invert(100%) recipe -- the untuned version read as a garish
// green/pink inversion artifact rather than a deliberate dark map.
//
// In light mode the filter is omitted so operators see the native OSM map.
export default function DarkTileLayer() {
  const { isLight } = useTheme();
  return (
    <TileLayer
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      className={isLight ? undefined : "dark-tiles"}
    />
  );
}
