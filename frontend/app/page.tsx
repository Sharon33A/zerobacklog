import { HealthStatus } from "@/components/health-status";

const pipelineStages = [
  { label: "Upload", detail: "Bring the backlog together" },
  { label: "Validate", detail: "Check quality and support" },
  { label: "Extract", detail: "Recover useful knowledge" },
  { label: "Analyze", detail: "Compare and connect ideas" },
  { label: "Decide", detail: "Prioritize, skip, or revisit" },
  { label: "Generate", detail: "Create learning assets" },
  { label: "Evaluate", detail: "Check output quality" },
  { label: "Retry", detail: "Regenerate selectively" },
  { label: "Store", detail: "Persist assets in B2" },
  { label: "Version", detail: "Keep provenance intact" },
  { label: "Download", detail: "Take the Action Pack" },
];

const backlogSources = [
  {
    index: "01",
    title: "Hours of saved video",
    copy: "Good intentions become an unsearchable watch-later queue.",
  },
  {
    index: "02",
    title: "Scattered study material",
    copy: "PDFs, screenshots, notes, and coding sheets repeat the same ground.",
  },
  {
    index: "03",
    title: "No confident next step",
    copy: "More resources create more decisions—not necessarily more learning.",
  },
];

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

function ArrowIcon() {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="18"
      viewBox="0 0 18 18"
      width="18"
    >
      <path d="M3.75 9h10.5M10 4.75 14.25 9 10 13.25" />
    </svg>
  );
}

export default function Home() {
  return (
    <div className="site-shell">
      <header className="site-header">
        <a className="brand-link" href="#top" aria-label="ZeroBacklog home">
          <BrandMark />
          <span>ZeroBacklog</span>
        </a>
        <HealthStatus />
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">
              <span aria-hidden="true" />
              A clearer way through your learning backlog
            </p>
            <h1 id="hero-title">
              Stop Saving.
              <span>Start Learning.</span>
            </h1>
            <p className="hero-promise">
              Upload everything you have been postponing. Leave with one clear
              learning path.
            </p>
            <div className="hero-actions">
              <button
                className="primary-button"
                type="button"
                disabled
                aria-describedby="action-pack-status"
              >
                Create My Action Pack
                <ArrowIcon />
              </button>
              <p id="action-pack-status">Coming in the hackathon MVP</p>
            </div>
          </div>

          <aside className="action-pack-preview" aria-label="Future Action Pack preview">
            <div className="preview-heading">
              <div>
                <p>Action Pack</p>
                <h2>Interview foundations</h2>
              </div>
              <span>Preview</span>
            </div>

            <div className="preview-focus">
              <p>Your next focus</p>
              <strong>Dynamic programming patterns</strong>
              <span>42 min · high impact</span>
            </div>

            <div className="preview-progress" aria-hidden="true">
              <span style={{ width: "68%" }} />
            </div>

            <dl className="preview-metrics">
              <div>
                <dt>Resources reduced</dt>
                <dd>18 → 6</dd>
              </div>
              <div>
                <dt>Time reclaimed</dt>
                <dd>7.4 hrs</dd>
              </div>
            </dl>

            <div className="preview-assets">
              <p>Planned learning assets</p>
              <ul>
                <li>
                  <span className="asset-icon">T</span>
                  Concise notes
                  <span>Planned</span>
                </li>
                <li>
                  <span className="asset-icon">D</span>
                  Visual map
                  <span>Planned</span>
                </li>
                <li>
                  <span className="asset-icon">V</span>
                  Voice lesson
                  <span>Planned</span>
                </li>
              </ul>
            </div>
          </aside>
        </section>

        <section className="problem-section" aria-labelledby="problem-title">
          <div className="section-intro">
            <p className="section-kicker">The knowledge-backlog problem</p>
            <h2 id="problem-title">
              Saving feels productive.
              <span> The backlog says otherwise.</span>
            </h2>
          </div>
          <ol className="problem-grid">
            {backlogSources.map((source) => (
              <li key={source.index}>
                <span>{source.index}</span>
                <h3>{source.title}</h3>
                <p>{source.copy}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="pipeline-section" aria-labelledby="pipeline-title">
          <div className="section-intro pipeline-intro">
            <div>
              <p className="section-kicker">The path ahead</p>
              <h2 id="pipeline-title">One accountable learning pipeline.</h2>
            </div>
            <p>
              Every future output is designed to stay traceable to its source,
              evaluated before delivery, and versioned when regenerated.
            </p>
          </div>

          <div className="pipeline-rail">
            <ol aria-label="Planned ZeroBacklog processing stages">
              {pipelineStages.map((stage, index) => (
                <li key={stage.label}>
                  <div className="stage-number">
                    {String(index + 1).padStart(2, "0")}
                  </div>
                  <h3>{stage.label}</h3>
                  <p>{stage.detail}</p>
                </li>
              ))}
            </ol>
          </div>
          <p className="pipeline-note">
            Pipeline shown for product direction; processing and generation
            stages are not implemented in this foundation milestone.
          </p>
        </section>
      </main>

      <footer>
        <div>
          <BrandMark />
          <p>
            <strong>ZeroBacklog</strong>
            <span>Built for learners ready to move forward.</span>
          </p>
        </div>
        <p>Backblaze Generative Media Hackathon · Foundation milestone</p>
      </footer>
    </div>
  );
}
