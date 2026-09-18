import { Clapperboard, FileVideo } from "lucide-react";

import { Badge, Tooltip } from "../../components/ui.jsx";

/**
 * Says plainly when the wall is replaying recorded footage. Government mode
 * runs real footage through the real pipeline; it is not a live city-scale
 * deployment and must never look like one.
 */
export default function ModeBadge({ governmentMode, demoMode }) {
  if (governmentMode) {
    return (
      <Tooltip
        content={`Recorded government CCTV footage relayed as live streams through the real pipeline${
          governmentMode.degraded ? ". Some cameras no longer point at the relay — re-enable government mode in Admin to repair." : "."
        }`}
      >
        <Badge tone={governmentMode.degraded ? "pending" : "signal"} icon={<FileVideo aria-hidden="true" />}>
          Recorded government footage
        </Badge>
      </Tooltip>
    );
  }
  if (demoMode) {
    return (
      <Tooltip content="Synthetic rehearsal footage for a screen recording.">
        <Badge tone="pending" icon={<Clapperboard aria-hidden="true" />}>
          Demo mode
        </Badge>
      </Tooltip>
    );
  }
  return null;
}
