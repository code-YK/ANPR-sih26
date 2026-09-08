/**
 * The Sentinel mark: a badge silhouette holding a CCTV camera. Original --
 * deliberately not a reproduction of any real government or department
 * emblem, which would misrepresent authorship.
 *
 * Same geometry as `public/favicon.svg`, kept as a component so the rail and
 * the sign-in card draw the identical mark rather than two drifting copies.
 * It is inline SVG rather than an <img> to the favicon so it inherits the
 * page's colours and can never be a second network request that fails on an
 * offline demo machine.
 *
 * `currentColor` is deliberately not used: the mark's blue and green are
 * fixed brand values, not text colour, and it sits on surfaces of several
 * different lightnesses.
 */
export default function SentinelMark({ size = 26, title = "Sentinel" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label={title}
      className="sentinel-mark"
    >
      <rect width="32" height="32" rx="7" fill="var(--ink-900)" />
      <path
        d="M16 3.6 L26.6 7.7 V15.7 C26.6 21.8 22 26.6 16 28.6 C10 26.6 5.4 21.8 5.4 15.7 V7.7 Z"
        fill="var(--ink-800)"
        stroke="var(--entity-bright)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <g
        stroke="var(--haze-100)"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      >
        <path d="M11.9 12.2 V10.2 H16.2" />
        <rect x="9.7" y="12.2" width="8.8" height="5.8" rx="1.5" fill="var(--ink-800)" />
      </g>
      <circle
        cx="20.8" cy="15.1" r="3.1"
        fill="var(--ink-800)" stroke="var(--haze-100)" strokeWidth="1.9"
      />
      <circle cx="20.8" cy="15.1" r="1.25" fill="var(--nominal)" />
    </svg>
  );
}
