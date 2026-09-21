import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const THEME_KEY = "citytrace-theme";
const ACCENT_KEY = "citytrace-accent";

/** Theme accent swatches — applied as --entity / --entity-bright in both modes */
export const ACCENT_COLORS = [
  { id: "default", label: "Default", hue: 210, sat: 90 },
  { id: "blue", label: "Blue", hue: 210, sat: 88 },
  { id: "cyan", label: "Cyan", hue: 192, sat: 88 },
  { id: "teal", label: "Teal", hue: 172, sat: 70 },
  { id: "green", label: "Green", hue: 145, sat: 65 },
  { id: "lime", label: "Lime", hue: 88, sat: 70 },
  { id: "yellow", label: "Yellow", hue: 48, sat: 92 },
  { id: "orange", label: "Orange", hue: 28, sat: 92 },
  { id: "red", label: "Red", hue: 4, sat: 78 },
  { id: "magenta", label: "Magenta", hue: 320, sat: 75 },
  { id: "purple", label: "Purple", hue: 275, sat: 72 },
  { id: "violet", label: "Violet", hue: 255, sat: 78 },
  { id: "brown", label: "Brown", hue: 25, sat: 45 },
];

const ACCENT_IDS = new Set(ACCENT_COLORS.map((c) => c.id));

function getInitialTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

function getInitialAccent() {
  try {
    const stored = localStorage.getItem(ACCENT_KEY);
    if (stored && ACCENT_IDS.has(stored)) return stored;
  } catch {
    /* ignore */
  }
  return "default";
}

function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function applyAccentVars(accentId, mode) {
  const entry = ACCENT_COLORS.find((c) => c.id === accentId) ?? ACCENT_COLORS[0];
  const { hue, sat } = entry;
  const root = document.documentElement;
  const isLight = mode === "light";

  const entityL = isLight ? 42 : 52;
  const brightL = isLight ? 36 : 68;
  const brightS = Math.min(100, sat + 5);

  const entity = `hsl(${hue} ${sat}% ${entityL}%)`;
  const bright = `hsl(${hue} ${brightS}% ${brightL}%)`;
  const soft = isLight ? `hsl(${hue} ${sat}% ${entityL}% / 0.1)` : `hsl(${hue} ${sat}% ${entityL}% / 0.14)`;
  const glow = isLight
    ? `0 0 8px hsl(${hue} ${sat}% ${entityL}% / 0.25)`
    : `0 0 12px hsl(${hue} ${sat}% ${entityL}% / 0.22)`;
  const entityHex = hslToHex(hue, sat, entityL);
  const brightHex = hslToHex(hue, brightS, brightL);

  root.style.setProperty("--accent-h", String(hue));
  root.style.setProperty("--accent-s", `${sat}%`);
  root.style.setProperty("--entity", entity);
  root.style.setProperty("--entity-bright", bright);
  root.style.setProperty("--entity-hex", entityHex);
  root.style.setProperty("--entity-bright-hex", brightHex);
  root.style.setProperty("--accent", entity);
  root.style.setProperty("--accent-bg", soft);
  root.style.setProperty("--glow-entity", glow);
  root.style.setProperty("--glow-accent", glow);
  /* Landing / command-stage palette follows the same accent */
  root.style.setProperty("--command-cyan", brightHex);
  root.style.setProperty("--command-blue", entityHex);
  root.setAttribute("data-accent", entry.id);
}

const ThemeContext = createContext({
  theme: "dark",
  setTheme: () => {},
  toggleTheme: () => {},
  isLight: false,
  accent: "default",
  setAccent: () => {},
  accents: ACCENT_COLORS,
});

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(getInitialTheme);
  const [accent, setAccentState] = useState(getInitialAccent);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
    applyAccentVars(accent, theme);
  }, [theme, accent]);

  const setTheme = useCallback((next) => {
    setThemeState(next === "light" ? "light" : "dark");
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === "light" ? "dark" : "light"));
  }, []);

  const setAccent = useCallback((id) => {
    if (!ACCENT_IDS.has(id)) return;
    setAccentState(id);
    try {
      localStorage.setItem(ACCENT_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme,
      isLight: theme === "light",
      accent,
      setAccent,
      accents: ACCENT_COLORS,
    }),
    [theme, setTheme, toggleTheme, accent, setAccent],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
