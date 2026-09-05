import { FlaskConical } from "lucide-react";

/**
 * Marks a row/card/marker whose backing event has `source === "simulator"` —
 * i.e. fabricated by the in-process demo generator (backend/app/simulator.py),
 * never a genuine detection. Always render this next to anything derived from
 * such an event; never let fabricated data look indistinguishable from real.
 */
export default function SimulatedBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`badge-simulated text-[9px] ${className}`}
      title="Fabricated by the demo simulator — not a genuine detection"
    >
      <FlaskConical size={9} className="inline mr-1 -mt-px" />
      SIMULATED
    </span>
  );
}

/** True when the given event/row's `source` field marks it as fabricated. */
export function isSimulated(source: string | null | undefined): boolean {
  return source === "simulator";
}
