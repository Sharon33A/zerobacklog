import Link from "next/link";
import { FlowProgress } from "@/components/flow-progress";
import { GenerationSetup } from "@/components/generation-setup";
import { HealthStatus } from "@/components/health-status";

export const metadata = {
  title: "Learner Profile — ZeroBacklog",
  description: "Optionally personalize and choose your ZeroBacklog outputs.",
};

export default function ProfilePage() {
  return (
    <div className="site-shell setup-shell">
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
      <main className="setup-page">
        <FlowProgress current={0} />
        <section className="setup-intro">
          <p className="eyebrow">
            <span aria-hidden="true" />
            Personalize only if useful
          </p>
          <h1>Decide what “done” should look like.</h1>
          <p>
            Your profile is optional. Your output choices are explicit, and
            failed media will never be shown as successfully generated.
          </p>
        </section>
        <GenerationSetup />
      </main>
    </div>
  );
}
