import Link from "next/link";
import { HealthStatus } from "@/components/health-status";
import { UploadForm } from "@/components/upload-form";
import { FlowProgress } from "@/components/flow-progress";

export const metadata = {
  title: "Resource Readiness — ZeroBacklog",
  description: "Upload, extract, and check learning resources for readiness.",
};

export default function UploadPage() {
  return (
    <div className="site-shell upload-shell">
      <header className="site-header">
        <Link className="brand-link" href="/" aria-label="Back to ZeroBacklog">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>ZeroBacklog</span>
        </Link>
        <HealthStatus />
      </header>

      <main className="upload-page">
        <FlowProgress current={1} />
        <section className="upload-intro" aria-labelledby="upload-title">
          <p className="eyebrow">
            <span aria-hidden="true" />
            Resource readiness
          </p>
          <h1 id="upload-title">Bring the backlog. Keep the clarity.</h1>
          <p>
            ZeroBacklog checks what is usable, relevant, readable, or repeated
            before anything enters your future learning plan.
          </p>
        </section>
        <UploadForm />
        <aside className="upload-privacy">
          <strong>You stay in control</strong>
          <p>
            Nothing is silently discarded. Remove, replace, retry, or include
            a flagged resource anyway.
          </p>
        </aside>
      </main>
    </div>
  );
}
