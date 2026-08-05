const FLOW_STEPS = [
  "Profile + outputs",
  "Files + links",
  "Resource readiness",
  "Action Pack",
  "Workflow + voice",
  "Versions + downloads",
];

export function FlowProgress({ current }: { current: number }) {
  return (
    <nav className="flow-progress" aria-label="ZeroBacklog workflow">
      <ol>
        {FLOW_STEPS.map((step, index) => (
          <li
            className={index < current ? "flow-complete" : ""}
            aria-current={index === current ? "step" : undefined}
            key={step}
          >
            <span>{index + 1}</span>
            {step}
          </li>
        ))}
      </ol>
    </nav>
  );
}
