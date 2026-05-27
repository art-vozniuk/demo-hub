// Mesh sampler-steps picker + cost hook, shared by the editor overlay and the
// Trellis demo. `multiplier` is display-only — the server re-resolves the
// final price at charge time from the trellis cost-multiplier table.

import { useEffect, useRef, useState } from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { pipelinesApi } from "@/api";
import type { MeshSteps } from "@/contexts/GenerationSessionContext";

export const MESH_QUALITY_OPTIONS: {
  label: string;
  steps: MeshSteps;
  multiplier: string;
}[] = [
  { label: "Low", steps: 4, multiplier: "×0.75" },
  { label: "Standard", steps: 8, multiplier: "×1" },
  { label: "High", steps: 12, multiplier: "×1.5" },
];

// Resolve the input-aware mesh cost server-side so the UI never drifts from
// the wallet handler. Stale responses are dropped via a token ref.
export function useMeshCost(
  steps: MeshSteps,
  enabled: boolean,
): number | undefined {
  const [cost, setCost] = useState<number | undefined>(undefined);
  const tokenRef = useRef(0);
  useEffect(() => {
    if (!enabled) return;
    const token = ++tokenRef.current;
    pipelinesApi
      .previewCost({ pipeline_name: "trellis", input: { steps } })
      .then((res) => {
        if (tokenRef.current === token) setCost(res.cost);
      })
      .catch(() => {
        if (tokenRef.current === token) setCost(undefined);
      });
  }, [steps, enabled]);
  return cost;
}

interface Props {
  value: MeshSteps;
  onChange: (steps: MeshSteps) => void;
  cost?: number;
}

export const MeshQualityPicker = ({ value, onChange, cost }: Props) => (
  <div className="space-y-1.5">
    <Label htmlFor="mesh-quality" className="text-xs">
      Quality
    </Label>
    <Select
      value={String(value)}
      onValueChange={(v) => onChange(Number(v) as MeshSteps)}
    >
      <SelectTrigger id="mesh-quality">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {MESH_QUALITY_OPTIONS.map((q) => (
          <SelectItem key={q.steps} value={String(q.steps)}>
            {q.label} · {q.steps} steps · {q.multiplier}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
    {cost !== undefined && (
      <p className="text-[11px] text-muted-foreground">
        Final cost:{" "}
        <span className="font-medium text-foreground tabular-nums">{cost}</span>{" "}
        token{cost === 1 ? "" : "s"}
      </p>
    )}
  </div>
);

export default MeshQualityPicker;
