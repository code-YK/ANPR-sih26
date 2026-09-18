import { Badge, Tooltip } from "../../components/ui.jsx";

/**
 * How a fact is known, stated in words. A catalogue's "live" flag is a claim
 * by the source, not proof this browser can play the stream; an approximate
 * geocode or inferred department is shown as such, never as confirmed.
 */
export function SourceLiveBadge({ value }) {
  if (value === true)
    return (
      <Tooltip content="Reported live by the source catalogue or last probe">
        <Badge tone="live">live</Badge>
      </Tooltip>
    );
  if (value === false) return <Badge tone="critical">offline</Badge>;
  return <Badge outline>unknown</Badge>;
}

export function SurveyBadge({ value }) {
  if (value === true) return <Badge>readable</Badge>;
  if (value === false) return <Badge>not readable</Badge>;
  return <Badge outline>not surveyed</Badge>;
}

export function GeocodeBadge({ value }) {
  if (value === "exact") return <Badge>exact</Badge>;
  if (value === "approximate")
    return (
      <Tooltip content="Estimated from a place name, not a surveyed coordinate">
        <Badge outline>approximate</Badge>
      </Tooltip>
    );
  if (value === "failed") return <Badge tone="pending">unplaced</Badge>;
  return <Badge outline>pending</Badge>;
}

export function InferredMark({ camera }) {
  if (camera.metadata_confidence !== "inferred") return null;
  return (
    <Tooltip content="Department or ownership was inferred from a place name, not a confirmed source">
      <Badge outline>inferred</Badge>
    </Tooltip>
  );
}
