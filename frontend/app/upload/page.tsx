import Link from "next/link";
import { HealthStatus } from "@/components/health-status";
import { UploadForm } from "@/components/upload-form";

export const metadata = {
  title: "Upload your backlog — ZeroBacklog",
  description: "Validate and store learning resources for ZeroBacklog.",
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
        <section className="upload-intro" aria-labelledby="upload-title">
          <p className="eyebrow">
            <span aria-hidden="true" />
            Upload and infrastructure milestone
          </p>
          <h1 id="upload-title">Bring the backlog together.</h1>
          <p>
            Files are validated before they are stored. Successful uploads are
            written to Backblaze B2 and recorded in Neon with a SHA-256
            fingerprint for duplicate detection.
          </p>
        </section>
        <UploadForm />
        <aside className="upload-privacy">
          <strong>What happens now</strong>
          <p>
            This milestone stores valid resources only. Analysis, summaries,
            and media generation are not running yet.
          </p>
        </aside>
      </main>
    </div>
  );
}
