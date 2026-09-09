// Hand-drawn SVG primitives for quantitative content.
//
// There is no charting library in this project and DESIGN.md §12 keeps it
// that way; the console's whole design layer is hand-written CSS smaller
// than any library that would replace it. These are deliberately the two
// simplest possible marks -- a stroke over time, and a length -- because
// colour in this console means urgency and nothing else, so a chart may not
// use hue to encode magnitude. Magnitude is length or position, always.

// A single stroke, no fill, no gradient, no axis furniture. It answers
// "which way is this going" at a glance and defers exact values to the
// number rendered beside it.
export function Sparkline({ values, width = 120, height = 28, title }) {
  if (!values || values.length === 0) return null;

  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;

  // 1px inset top and bottom so a flat line at the extreme is not clipped
  // to invisibility against the edge of the box.
  const points = values
    .map((value, index) => {
      const x = index * step;
      const y = height - 1 - ((value - min) / span) * (height - 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={title}
    >
      {title && <title>{title}</title>}
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// Magnitude as length against the largest value in the same set. `max` is
// passed in rather than derived per-row so every bar in a table shares one
// scale -- bars normalised per row would make a 2 and a 200 look identical.
export function VolumeBar({ value, max, title }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <span className="volume-bar" title={title}>
      <span className="volume-bar-fill" style={{ width: `${pct}%` }} />
    </span>
  );
}
