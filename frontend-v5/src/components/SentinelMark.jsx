/**
 * The Sentinel mark: a lens inside a hexagonal housing. Original geometry --
 * deliberately not any government or department emblem.
 */
export default function SentinelMark({ size = 28, title = "Sentinel" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={title}>
      <rect width="32" height="32" rx="8" fill="oklch(34% 0.008 285)" />
      <path
        d="M9 11.5 16 7l7 4.5v9L16 25l-7-4.5z"
        fill="none"
        stroke="oklch(94.5% 0.004 285)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="16" r="3.2" fill="oklch(74% 0.1 268)" />
      <circle cx="16" cy="16" r="1.2" fill="oklch(27.5% 0.006 285)" />
    </svg>
  );
}
