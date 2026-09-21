import { useId } from "react";

/**
 * CityTraceAI mark — city skyline with a live trace path.
 */
export default function BrandMark({ size = 28, title = "CityTraceAI" }) {
  const gid = useId().replace(/:/g, "");
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label={title}
      className="brand-mark"
    >
      <defs>
        <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--entity-bright)" />
          <stop offset="100%" stopColor="var(--entity)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gid})`} />
      <path
        d="M6 22 V14 H9 V22 M11 22 V10 H15 V22 M17 22 V13 H20 V22 M22 22 V8 H26 V22"
        fill="none"
        stroke="rgba(255,255,255,0.92)"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 24 C12 24 14 20 17 18 C20 16 23 17 25 15"
        fill="none"
        stroke="rgba(255,255,255,0.95)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="25" cy="15" r="2.1" fill="#fff" />
    </svg>
  );
}
