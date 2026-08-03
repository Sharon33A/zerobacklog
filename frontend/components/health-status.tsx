"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/config";
import type { HealthResponse } from "@/types/health";

type HealthState =
  | { kind: "loading" }
  | { kind: "success"; health: HealthResponse }
  | { kind: "failure" };

const REQUEST_TIMEOUT_MS = 5_000;

function isHealthResponse(value: unknown): value is HealthResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.service === "string" &&
    candidate.status === "ok" &&
    typeof candidate.version === "string" &&
    typeof candidate.environment === "string"
  );
}

export function HealthStatus() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  const checkHealth = useCallback(async () => {
    setState({ kind: "loading" });
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error("The health endpoint returned an unsuccessful status.");
      }

      const health: unknown = await response.json();
      if (!isHealthResponse(health)) {
        throw new Error("The health endpoint returned an unexpected response.");
      }

      setState({ kind: "success", health });
    } catch {
      setState({ kind: "failure" });
    } finally {
      window.clearTimeout(timeoutId);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
  }, [checkHealth]);

  if (state.kind === "loading") {
    return (
      <div className="health-status health-loading" role="status" aria-live="polite">
        <span className="health-dot" aria-hidden="true" />
        <span>
          <strong>Checking API</strong>
          <small>Please wait</small>
        </span>
      </div>
    );
  }

  if (state.kind === "failure") {
    return (
      <div className="health-status health-failure" role="status" aria-live="polite">
        <span className="health-dot" aria-hidden="true" />
        <span>
          <strong>API unavailable</strong>
          <small>Start the backend, then retry</small>
        </span>
        <button type="button" onClick={() => void checkHealth()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="health-status health-success" role="status" aria-live="polite">
      <span className="health-dot" aria-hidden="true" />
      <span>
        <strong>API connected</strong>
        <small>
          {state.health.environment} · v{state.health.version}
        </small>
      </span>
    </div>
  );
}
