"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/config";
import { LearningWorkflow } from "@/components/learning-workflow";
import {
  DEFAULT_GENERATION_SETTINGS,
  GENERATION_SETTINGS_KEY,
  OUTPUT_OPTIONS,
  formatProfileSummary,
  parseGenerationSettings,
} from "@/lib/generation-settings";
import type { GenerationSettings } from "@/lib/generation-settings";
import type {
  ActionPackResponse,
  EvidenceReference,
  GeneratedAsset,
} from "@/types/action-pack";
import type { ApiErrorResponse } from "@/types/upload";

const STAGES = [
  "Validate",
  "Extract",
  "Analyze",
  "Compare",
  "Decide",
  "Build Action Pack",
  "Generate selected learning assets",
  "Evaluate outputs",
  "Store versions",
];

async function readResponse(response: Response): Promise<ActionPackResponse> {
  const payload = (await response.json()) as
    | ActionPackResponse
    | ApiErrorResponse;
  if (!response.ok || !("action_pack" in payload)) {
    throw new Error(
      "error" in payload && payload.error?.message
        ? payload.error.message
        : "The Action Pack could not be generated.",
    );
  }
  return payload;
}

async function readAssetResponse(response: Response): Promise<GeneratedAsset> {
  const payload = (await response.json()) as GeneratedAsset | ApiErrorResponse;
  if (!response.ok || !("versions" in payload)) {
    throw new Error(
      "error" in payload && payload.error?.message
        ? payload.error.message
        : "The asset action could not be completed.",
    );
  }
  return payload;
}

function assetUrl(path: string | null): string | undefined {
  return path ? `${API_BASE_URL}${path}` : undefined;
}

function GeneratedAssetsPanel({
  result,
  activeAsset,
  onRegenerate,
  onRestore,
}: {
  result: ActionPackResponse;
  activeAsset: string | null;
  onRegenerate: (asset: GeneratedAsset) => Promise<void>;
  onRestore: (asset: GeneratedAsset, version: number) => Promise<void>;
}) {
  const [comparison, setComparison] = useState<string | null>(null);

  if (result.assets.length === 0) return null;

  return (
    <section className="generated-assets" aria-labelledby="generated-assets-title">
      <div className="generated-assets-heading">
        <div>
          <p className="section-kicker">Generated outputs</p>
          <h2 id="generated-assets-title">Your learning media, with receipts.</h2>
          <p>
            Every version is stored separately with generation settings,
            evaluation, and source provenance.
          </p>
        </div>
        <a
          className="asset-download-primary"
          href={`${API_BASE_URL}/api/v1/action-packs/${result.id}/download.zip`}
        >
          Download combined ZIP
        </a>
      </div>

      <div className="generated-asset-list">
        {result.assets.map((asset) => {
          const current =
            asset.versions.find((version) => version.is_current) ??
            asset.versions[0];
          const canRegenerate = ["note", "learning_workflow", "voice"].includes(
            asset.asset_type,
          );
          return (
            <article
              className={`generated-asset-card asset-${asset.asset_type} asset-${
                current?.status || "pending"
              }`}
              key={asset.id}
            >
              <header>
                <div>
                  <span>{asset.asset_type.replaceAll("_", " ")}</span>
                  <h3>{asset.display_name}</h3>
                </div>
                <strong
                  className={`asset-status asset-status-${
                    current?.status || "pending"
                  }`}
                >
                  {current?.status === "stored"
                    ? `Stored · V${current.version_number}`
                    : current?.status || "Pending"}
                </strong>
              </header>

              {current?.status === "stored" &&
                asset.asset_type === "learning_workflow" &&
                current.download_url && (
                <LearningWorkflow
                  downloadUrl={assetUrl(current.download_url) ?? ""}
                  version={current.version_number}
                />
              )}
              {current?.status === "stored" && asset.asset_type === "voice" && (
                <audio controls preload="metadata">
                  <source
                    src={assetUrl(current.download_url)}
                    type={current.mime_type}
                  />
                  Your browser does not support audio playback.
                </audio>
              )}
              {current?.status === "failed" && (
                <div className="asset-failure" role="status">
                  <strong>Generation failed</strong>
                  <p>
                    {current.failure_message ||
                      "No verified learning asset was stored for this version."}
                  </p>
                  {current.failure_message && (
                    <details>
                      <summary>Provider details</summary>
                      <code>{current.failure_message}</code>
                    </details>
                  )}
                </div>
              )}

              {current && (
                <>
                  <dl className="asset-metadata">
                    <div>
                      <dt>Confidence</dt>
                      <dd>
                        {current.confidence === null
                          ? "Not scored"
                          : `${Math.round(current.confidence * 100)}%`}
                      </dd>
                    </div>
                    <div>
                      <dt>Generation time</dt>
                      <dd>
                        {current.generation_time_ms === null
                          ? "Unavailable"
                          : `${(current.generation_time_ms / 1000).toFixed(1)}s`}
                      </dd>
                    </div>
                    <div>
                      <dt>Storage</dt>
                      <dd>
                        {current.status === "stored"
                          ? "Stored in B2 · versioned"
                          : current.status}
                      </dd>
                    </div>
                  </dl>
                  {current.confidence !== null && current.confidence < 0.72 && (
                    <p className="quality-warning">
                      Generation quality is below the recommended confidence.
                    </p>
                  )}
                  {current.evaluation_summary && (
                    <p className="asset-evaluation">
                      {current.evaluation_summary}
                    </p>
                  )}
                  <details className="asset-provenance">
                    <summary>Generated from and provenance</summary>
                    <p>
                      {current.provenance.classification.replaceAll("_", " ")} ·{" "}
                      {new Date(
                        current.provenance.generation_timestamp,
                      ).toLocaleString()}{" "}
                      · version {current.provenance.version_number}
                    </p>
                    <ul>
                      {current.provenance.resources.map((resource) => (
                        <li key={resource.resource_id}>
                          <strong>{resource.title}</strong>
                          <code>{resource.resource_id}</code>
                          {resource.link && (
                            <a href={resource.link} target="_blank" rel="noreferrer">
                              Source link
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                    <small>
                      {current.provenance.evidence_references.length} evidence
                      reference(s) · Genblaze run{" "}
                      {current.genblaze_run_id || "unavailable"}
                    </small>
                  </details>
                </>
              )}

              <div className="asset-actions">
                {current?.download_url && (
                  <a href={assetUrl(current.download_url)}>
                    {asset.asset_type === "learning_workflow"
                      ? "Download workflow JSON"
                      : "Download this version"}
                  </a>
                )}
                {canRegenerate && (
                  <button
                    type="button"
                    disabled={activeAsset === asset.id}
                    onClick={() => void onRegenerate(asset)}
                  >
                    {activeAsset === asset.id
                      ? "Generating..."
                      : asset.asset_type === "learning_workflow"
                        ? "Regenerate only this workflow"
                        : `Regenerate only this ${asset.asset_type}`}
                  </button>
                )}
                {asset.versions.length > 1 && (
                  <button
                    type="button"
                    aria-expanded={comparison === asset.id}
                    onClick={() =>
                      setComparison((value) =>
                        value === asset.id ? null : asset.id,
                      )
                    }
                  >
                    Compare versions
                  </button>
                )}
              </div>

              <details className="version-history" open={asset.versions.length > 1}>
                <summary>Version history ({asset.versions.length})</summary>
                <div>
                  {asset.versions.map((version) => (
                    <article key={version.id}>
                      <strong>
                        Version {version.version_number}
                        {version.is_current ? " · current" : ""}
                      </strong>
                      <span>{new Date(version.created_at).toLocaleString()}</span>
                      <span>
                        {version.model} ·{" "}
                        {version.confidence === null
                          ? "not scored"
                          : `${Math.round(version.confidence * 100)}% confidence`}
                      </span>
                      <span>
                        Settings: {JSON.stringify(version.generation_settings)}
                      </span>
                      <span>Storage: {version.status}</span>
                      <div>
                        {version.download_url && (
                          <a href={assetUrl(version.download_url)}>Download</a>
                        )}
                        {!version.is_current && version.status === "stored" && (
                          <button
                            type="button"
                            onClick={() =>
                              void onRestore(asset, version.version_number)
                            }
                          >
                            Restore
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </details>

              {comparison === asset.id && asset.versions.length > 1 && (
                <div className="version-comparison">
                  {asset.versions.slice(0, 2).map((version) => (
                    <div key={version.id}>
                      <strong>Version {version.version_number}</strong>
                      <span>{version.model}</span>
                      <span>
                        {version.confidence === null
                          ? "Not scored"
                          : `${Math.round(version.confidence * 100)}% confidence`}
                      </span>
                      <p>{version.evaluation_summary}</p>
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceDrawer({
  evidence,
}: {
  evidence: EvidenceReference[];
}) {
  return (
    <details className="evidence-drawer">
      <summary>
        Evidence <span>{evidence.length}</span>
      </summary>
      <ul>
        {evidence.map((item, index) => (
          <li key={`${item.resource_id}-${index}`}>
            <div>
              <strong>{item.title}</strong>
              <span>
                {Math.round(item.confidence * 100)}% ·{" "}
                {item.basis === "source_derived"
                  ? "Source-derived"
                  : "AI-inferred"}
              </span>
            </div>
            <p>{item.support}</p>
            <code>{item.resource_id}</code>
            {item.location && <small>{item.location}</small>}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ActionPackResults({ projectId }: { projectId: string }) {
  const [result, setResult] = useState<ActionPackResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [generationSettings, setGenerationSettings] =
    useState<GenerationSettings>({
      ...DEFAULT_GENERATION_SETTINGS,
      output_options: [...DEFAULT_GENERATION_SETTINGS.output_options],
    });
  const [activeAsset, setActiveAsset] = useState<string | null>(null);

  useEffect(() => {
    setGenerationSettings(
      parseGenerationSettings(
        window.localStorage.getItem(GENERATION_SETTINGS_KEY),
      ),
    );

    void fetch(
      `${API_BASE_URL}/api/v1/projects/${projectId}/action-packs/latest`,
    )
      .then(async (response) => {
        if (response.status === 404) return null;
        return readResponse(response);
      })
      .then((payload) => setResult(payload))
      .catch((caught) =>
        setError(
          caught instanceof Error
            ? caught.message
            : "The latest Action Pack could not be loaded.",
        ),
      )
      .finally(() => setIsLoading(false));
  }, [projectId]);

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsGenerating(true);
    setError(null);
    setStage(0);
    const timer = window.setInterval(
      () => setStage((current) => Math.min(current + 1, STAGES.length - 1)),
      5500,
    );
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/projects/${projectId}/action-packs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            learner_profile: generationSettings.learner_profile,
            output_options: generationSettings.output_options,
            workflow_focus_topics:
              generationSettings.workflow_focus_topics,
            voice_mode: generationSettings.voice_mode,
          }),
        },
      );
      setResult(await readResponse(response));
      setStage(STAGES.length - 1);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The Action Pack could not be generated.",
      );
    } finally {
      window.clearInterval(timer);
      setIsGenerating(false);
    }
  }

  function replaceAsset(updated: GeneratedAsset) {
    setResult((current) =>
      current
        ? {
            ...current,
            assets: current.assets.map((asset) =>
              asset.id === updated.id ? updated : asset,
            ),
          }
        : current,
    );
  }

  async function regenerateAsset(asset: GeneratedAsset) {
    setActiveAsset(asset.id);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/generated-assets/${asset.id}/regenerate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            voice_mode:
              asset.asset_type === "voice"
                ? generationSettings.voice_mode
                : null,
            workflow_mode:
              asset.asset_type === "learning_workflow"
                ? asset.versions.find((version) => version.is_current)
                    ?.generation_settings.workflow_mode === "concise"
                  ? "guided"
                  : "concise"
                : null,
          }),
        },
      );
      const updated = await readAssetResponse(response);
      replaceAsset(updated);
      if (updated.versions[0]?.status === "failed") {
        setError(
          updated.versions[0].failure_message ||
            "Regeneration failed; the previous version remains current.",
        );
      }
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Regeneration failed.",
      );
    } finally {
      setActiveAsset(null);
    }
  }

  async function restoreAsset(asset: GeneratedAsset, version: number) {
    setActiveAsset(asset.id);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/generated-assets/${asset.id}/versions/${version}/restore`,
        { method: "POST" },
      );
      replaceAsset(await readAssetResponse(response));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Restore failed.");
    } finally {
      setActiveAsset(null);
    }
  }

  if (isLoading) {
    return (
      <main className="results-loading" aria-live="polite">
        <span className="health-dot" />
        Loading the latest real Action Pack...
      </main>
    );
  }

  return (
    <main className="results-page">
      <section className="results-hero">
        <div>
          <p className="eyebrow">
            <span aria-hidden="true" />
            Real cross-resource result
          </p>
          <h1>{result?.action_pack.title || "Build your first Action Pack."}</h1>
          <p>
            {result?.action_pack.executive_summary ||
              "ZeroBacklog will compare only ready or explicitly approved resources."}
          </p>
        </div>
        <Link href="/upload">Back to resources</Link>
      </section>

      <form className="generation-summary" onSubmit={generate}>
        <div>
          <p className="section-kicker">Ready to build</p>
          <h2>Your saved learning setup</h2>
          <div className="profile-summary" aria-label="Learner profile summary">
            {formatProfileSummary(generationSettings.learner_profile).map(
              (item) => (
                <span key={item}>{item}</span>
              ),
            )}
          </div>
          <p className="language-support-note">
            English analysis is primary. Other preferred languages are
            best-effort for generated text and voice.
          </p>
        </div>
        <div className="selected-output-summary">
          <strong>Selected outputs</strong>
          <ul>
            {OUTPUT_OPTIONS.filter((option) =>
              generationSettings.output_options.includes(option.value),
            ).map((option) => (
              <li key={option.value}>{option.label}</li>
            ))}
          </ul>
          <Link href="/profile">Edit profile or output choices</Link>
        </div>
        <button
          type="submit"
          disabled={
            isGenerating || generationSettings.output_options.length === 0
          }
        >
          {isGenerating
            ? `${STAGES[stage]}...`
            : result
              ? "Build a new Action Pack"
              : "Build Action Pack"}
        </button>
      </form>

      {isGenerating && (
        <ol className="processing-stages" aria-label="Processing stages">
          {STAGES.map((label, index) => (
            <li
              className={
                index < stage ? "stage-done" : index === stage ? "stage-active" : ""
              }
              key={label}
            >
              <span>{index + 1}</span>
              {label}
            </li>
          ))}
        </ol>
      )}

      {error && (
        <div className="results-error" role="alert">
          <strong>Action Pack not completed</strong>
          <p>{error}</p>
        </div>
      )}

      {!result && !isGenerating ? (
        <section className="results-empty">
          <strong>No generated result is shown yet.</strong>
          <p>
            Build the Action Pack to replace this state with evidence-backed
            Gemini output.
          </p>
        </section>
      ) : (
        result && (
          <>
            <GeneratedAssetsPanel
              result={result}
              activeAsset={activeAsset}
              onRegenerate={regenerateAsset}
              onRestore={restoreAsset}
            />
            <div className="action-pack-sections">
            <section className="result-section reduction-summary section-backlog">
              <p className="section-kicker">Backlog reduction</p>
              <div className="result-metrics">
                <div>
                  <strong>
                    {result.action_pack.backlog_reduction.resource_count}
                  </strong>
                  <span>resources compared</span>
                </div>
                <div>
                  <strong>
                    {result.action_pack.backlog_reduction
                      .estimated_original_minutes ?? "—"}
                  </strong>
                  <span>estimated minutes</span>
                </div>
                <div>
                  <strong>
                    {result.action_pack.backlog_reduction.repeated_content_percentage}%
                  </strong>
                  <span>repeated content</span>
                </div>
              </div>
              <small>
                {result.action_pack.backlog_reduction.metric_methodology}
              </small>
            </section>

            <section className="result-section start-here">
              <p className="section-kicker">Start here</p>
              <h2>{result.action_pack.start_here.topic_or_resource}</h2>
              <p>{result.action_pack.start_here.why}</p>
              {result.action_pack.start_here.estimated_minutes !== null && (
                <span>
                  {result.action_pack.start_here.estimated_minutes} minutes
                </span>
              )}
              <EvidenceDrawer evidence={result.action_pack.start_here.evidence} />
            </section>

            <section className="result-section section-skip">
              <p className="section-kicker">What to skip</p>
              <div className="result-card-grid">
                {result.action_pack.backlog_reduction.skippable_resources.map(
                  (resource) => (
                    <article key={resource.resource_id}>
                      <h3>{resource.title}</h3>
                      <p>{resource.reason}</p>
                      <EvidenceDrawer evidence={resource.evidence} />
                    </article>
                  ),
                )}
                {result.action_pack.backlog_reduction.skippable_resources
                  .length === 0 && <p>No resource is safely skippable yet.</p>}
              </div>
            </section>

            <section className="result-section section-common">
              <p className="section-kicker">Common topics</p>
              <div className="result-card-grid">
                {result.action_pack.common_topics.map((topic) => (
                  <article key={topic.topic}>
                    <span>{topic.source_count} sources</span>
                    <h3>{topic.topic}</h3>
                    <p>{topic.explanation}</p>
                    <EvidenceDrawer evidence={topic.evidence} />
                  </article>
                ))}
              </div>
            </section>

            <section className="result-section section-unique">
              <p className="section-kicker">Unique insights</p>
              <div className="result-card-grid">
                {result.action_pack.unique_insights.map((insight) => (
                  <article key={insight.insight}>
                    <h3>{insight.insight}</h3>
                    <p>{insight.why_it_matters}</p>
                    <EvidenceDrawer evidence={insight.evidence} />
                  </article>
                ))}
              </div>
            </section>

            <section className="result-section section-conflicts">
              <p className="section-kicker">Conflicts</p>
              <div className="result-card-grid">
                {result.action_pack.contradictions.map((conflict) => (
                  <article key={conflict.topic}>
                    <h3>{conflict.topic}</h3>
                    {conflict.sides.map((side) => (
                      <div key={side.position}>
                        <p>{side.position}</p>
                        <EvidenceDrawer evidence={side.evidence} />
                      </div>
                    ))}
                    <p>{conflict.neutral_explanation}</p>
                    {conflict.recommendation && (
                      <strong>{conflict.recommendation}</strong>
                    )}
                  </article>
                ))}
                {result.action_pack.contradictions.length === 0 && (
                  <p>No source-supported contradiction was found.</p>
                )}
              </div>
            </section>

            <section className="result-section section-notes">
              <p className="section-kicker">Merged notes</p>
              {result.action_pack.merged_notes.map((note) => (
                <article className="merged-note" key={note.topic}>
                  <h3>{note.topic}</h3>
                  <ul>
                    {note.concise_notes.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  {note.syntax_or_pseudocode && (
                    <pre>{note.syntax_or_pseudocode}</pre>
                  )}
                  <div>
                    <p>
                      <strong>Recognition clues:</strong>{" "}
                      {note.recognition_clues.join("; ") || "None identified"}
                    </p>
                    <p>
                      <strong>Common mistakes:</strong>{" "}
                      {note.common_mistakes.join("; ") || "None identified"}
                    </p>
                    <p>
                      <strong>Memory cues:</strong>{" "}
                      {note.memory_cues.join("; ") || "None identified"}
                    </p>
                  </div>
                  <EvidenceDrawer evidence={note.evidence} />
                </article>
              ))}
            </section>

            <section className="result-section section-problems">
              <p className="section-kicker">Priority problems</p>
              <div className="result-card-grid">
                {result.action_pack.priority_problems.map((problem) => (
                  <article key={problem.normalized_name}>
                    <span>{problem.priority.replace("_", " ")}</span>
                    <h3>{problem.normalized_name}</h3>
                    <p>{problem.reason}</p>
                    {problem.aliases.length > 0 && (
                      <small>Also named: {problem.aliases.join(", ")}</small>
                    )}
                    <EvidenceDrawer evidence={problem.evidence} />
                  </article>
                ))}
                {result.action_pack.priority_problems.length === 0 && (
                  <p>No named coding problems were supported by the sources.</p>
                )}
              </div>
            </section>

            <section className="result-section section-verdicts">
              <p className="section-kicker">Resource verdicts</p>
              <div className="verdict-list">
                {result.action_pack.resource_verdicts.map((verdict) => (
                  <article key={verdict.resource_id}>
                    <span>{verdict.verdict.replaceAll("_", " ")}</span>
                    <h3>{verdict.title}</h3>
                    <p>{verdict.reason}</p>
                    {verdict.selected_sections.length > 0 && (
                      <small>
                        Use: {verdict.selected_sections.join(", ")}
                      </small>
                    )}
                    <EvidenceDrawer evidence={verdict.evidence} />
                  </article>
                ))}
              </div>
            </section>
            </div>
          </>
        )
      )}
    </main>
  );
}
