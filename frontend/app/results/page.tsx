import { ActionPackResults } from "@/components/action-pack-results";
import { HealthStatus } from "@/components/health-status";
import Link from "next/link";
import { FlowProgress } from "@/components/flow-progress";

export const metadata = {
  title: "Your Action Pack — ZeroBacklog",
  description: "A real evidence-first reduction of your learning backlog.",
};

export default async function ResultsPage({
  searchParams,
}: {
  searchParams: Promise<{ project_id?: string }>;
}) {
  const { project_id: projectId } = await searchParams;

  return (
    <div className="site-shell results-shell">
      <header className="site-header">
        <Link className="brand-link" href="/" aria-label="ZeroBacklog home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>ZeroBacklog</span>
        </Link>
        <HealthStatus />
      </header>
      <FlowProgress current={3} />
      {projectId ? (
        <ActionPackResults projectId={projectId} />
      ) : (
        <main className="results-empty">
          <strong>No project selected.</strong>
          <p>Return to Resource Readiness and choose at least two resources.</p>
          <Link href="/upload">Open Resource Readiness</Link>
        </main>
      )}
    </div>
  );
}
