import type { Section } from "../../types/api";

export interface PlanViewProps {
  initialSections: Section[];
}

// PlanView stub — full implementation in N2-S15.
// Accepts initialSections prop (from App.tsx / GET /state) but does not yet render them.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export default function PlanView(_props: PlanViewProps) {
  return (
    <div data-testid="plan-view">
      <h2>Plan</h2>
    </div>
  );
}
