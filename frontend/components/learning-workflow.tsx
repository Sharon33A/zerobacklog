"use client";

import { useEffect, useState } from "react";
import type {
  LearningWorkflowAsset,
  LearningWorkflowStage,
} from "@/types/action-pack";

const TONES = new Set<LearningWorkflowStage["tone"]>([
  "teal",
  "blue",
  "violet",
  "amber",
  "coral",
  "green",
  "navy",
]);

function isLearningWorkflow(value: unknown): value is LearningWorkflowAsset {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LearningWorkflowAsset>;
  return (
    candidate.schema_version === 1 &&
    typeof candidate.title === "string" &&
    Array.isArray(candidate.stages) &&
    candidate.stages.length > 0
  );
}

function toneClass(tone: LearningWorkflowStage["tone"]): string {
  return TONES.has(tone) ? `workflow-tone-${tone}` : "workflow-tone-navy";
}

export function LearningWorkflow({
  downloadUrl,
  version,
}: {
  downloadUrl: string;
  version: number;
}) {
  const [workflow, setWorkflow] = useState<LearningWorkflowAsset | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setWorkflow(null);
    setError(null);

    void fetch(downloadUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("The stored workflow could not be loaded.");
        }
        const payload: unknown = await response.json();
        if (!isLearningWorkflow(payload)) {
          throw new Error("The stored workflow has an unexpected format.");
        }
        setWorkflow(payload);
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setError(
          caught instanceof Error
            ? caught.message
            : "The stored workflow could not be loaded.",
        );
      });

    return () => controller.abort();
  }, [downloadUrl, version]);

  if (error) {
    return (
      <div className="workflow-load-state workflow-load-error" role="alert">
        <strong>Workflow preview unavailable</strong>
        <p>{error} The downloadable version remains available.</p>
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="workflow-load-state" aria-live="polite">
        Loading the stored Learning Workflow...
      </div>
    );
  }

  return (
    <section
      className="learning-workflow-preview"
      aria-labelledby={`workflow-title-${version}`}
    >
      <header>
        <div>
          <p>Action Pack roadmap · Version {version}</p>
          <h4 id={`workflow-title-${version}`}>{workflow.title}</h4>
          <span>{workflow.summary}</span>
        </div>
        <div className="workflow-header-meta">
          <strong>{workflow.stages.length} stages</strong>
          <span>{workflow.mode} route</span>
        </div>
      </header>

      <ol className="workflow-timeline">
        {workflow.stages.map((stage, index) => (
          <li
            className={`workflow-stage ${toneClass(stage.tone)}`}
            key={stage.stage_id}
          >
            <span className="workflow-stage-number" aria-hidden="true">
              {index + 1}
            </span>
            <details open={index === 0}>
              <summary>
                <span>
                  <small>{stage.label}</small>
                  <strong>{stage.headline}</strong>
                </span>
                <span className="workflow-expand-label">Open</span>
              </summary>
              <div className="workflow-stage-content">
                <p>{stage.summary}</p>
                <ul>
                  {stage.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <footer>
                  {stage.estimated_minutes !== null && (
                    <span>{stage.estimated_minutes} min</span>
                  )}
                  <span>{stage.evidence.length} evidence reference(s)</span>
                </footer>
              </div>
            </details>
            {index < workflow.stages.length - 1 && (
              <span className="workflow-arrow" aria-hidden="true">
                ↓
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
