"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "@/lib/config";
import type {
  ApiErrorResponse,
  LinkReadiness,
  LinkResponse,
  ResourceListResponse,
  ResourceReadiness,
  ResourceResponse,
  UploadResponse,
} from "@/types/upload";

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const PROJECT_STORAGE_KEY = "zerobacklog-project-id";

type Notice = {
  id: string;
  kind: "success" | "failure";
  message: string;
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatStatus(resource: ResourceReadiness): string {
  if (resource.approved) return "Included";
  if (resource.marked_for_replacement) return "Replace";
  if (resource.readiness_status) {
    return resource.readiness_status.replace("_", " ");
  }
  return resource.lifecycle_state.replaceAll("_", " ");
}

function toneFor(resource: ResourceReadiness): string {
  if (resource.eligible_for_analysis) return "readiness-ready";
  if (
    resource.readiness_status === "partial" ||
    resource.readiness_status === "low_confidence"
  ) {
    return "readiness-warning";
  }
  if (resource.readiness_status === "failed") return "readiness-failed";
  return "readiness-action";
}

function toneForLink(link: LinkReadiness): string {
  if (link.eligible_for_analysis) return "readiness-ready";
  if (link.status === "partial") return "readiness-warning";
  if (link.status === "failed") return "readiness-failed";
  return "readiness-action";
}

async function readApiResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T | ApiErrorResponse;
  if (!response.ok) {
    const apiError = payload as ApiErrorResponse;
    throw new Error(
      apiError.error?.message || "The request could not be completed.",
    );
  }
  return payload as T;
}

export function UploadForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [resources, setResources] = useState<ResourceReadiness[]>([]);
  const [links, setLinks] = useState<LinkReadiness[]>([]);
  const [linkUrl, setLinkUrl] = useState("");
  const [isAddingLink, setIsAddingLink] = useState(false);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [activeFile, setActiveFile] = useState<number | null>(null);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [detailsId, setDetailsId] = useState<string | null>(null);

  const invalidSelection = useMemo(
    () => files.find((file) => file.size > MAX_FILE_SIZE),
    [files],
  );
  const eligibleCount =
    resources.filter((resource) => resource.eligible_for_analysis).length +
    links.filter((link) => link.eligible_for_analysis).length;
  const isUploading = activeFile !== null;

  useEffect(() => {
    const existing = window.localStorage.getItem(PROJECT_STORAGE_KEY);
    const localProjectId = existing || window.crypto.randomUUID();
    if (!existing) {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, localProjectId);
    }
    setProjectId(localProjectId);

    void fetch(`${API_BASE_URL}/api/v1/projects/${localProjectId}/resources`)
      .then((response) => readApiResponse<ResourceListResponse>(response))
      .then((payload) => {
        setResources(payload.resources);
        setLinks(payload.links);
      })
      .catch(() => {
        // A new project or an offline backend legitimately has no list yet.
      });
  }, []);

  function upsertResource(resource: ResourceReadiness) {
    setResources((current) => {
      const remaining = current.filter((item) => item.id !== resource.id);
      return [...remaining, resource].sort((left, right) =>
        left.created_at.localeCompare(right.created_at),
      );
    });
  }

  function upsertLink(link: LinkReadiness) {
    setLinks((current) => {
      const remaining = current.filter((item) => item.id !== link.id);
      return [...remaining, link].sort((left, right) =>
        left.created_at.localeCompare(right.created_at),
      );
    });
  }

  async function processResource(resourceId: string) {
    setActiveAction(resourceId);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/resources/${resourceId}/process`,
        { method: "POST" },
      );
      const payload = await readApiResponse<ResourceResponse>(response);
      upsertResource(payload.resource);
    } finally {
      setActiveAction(null);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length || invalidSelection || isUploading || !projectId) return;

    setNotices([]);
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      setActiveFile(index);
      const formData = new FormData();
      formData.append("file", file);
      formData.append("project_id", projectId);

      try {
        const uploadResponse = await fetch(`${API_BASE_URL}/api/v1/uploads`, {
          method: "POST",
          body: formData,
        });
        const uploadPayload =
          await readApiResponse<UploadResponse>(uploadResponse);
        await processResource(uploadPayload.upload.id);
        setNotices((current) => [
          ...current,
          {
            id: uploadPayload.upload.id,
            kind: "success",
            message: `${file.name} was stored and checked.`,
          },
        ]);
      } catch (error) {
        setNotices((current) => [
          ...current,
          {
            id: `${file.name}-${index}`,
            kind: "failure",
            message:
              error instanceof Error
                ? `${file.name}: ${error.message}`
                : `${file.name}: processing failed.`,
          },
        ]);
      }
    }
    setActiveFile(null);
    setFiles([]);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleLinkSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !linkUrl.trim() || isAddingLink) return;
    setIsAddingLink(true);
    setNotices([]);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/links`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, url: linkUrl.trim() }),
      });
      const payload = await readApiResponse<LinkResponse>(response);
      upsertLink(payload.link);
      setLinkUrl("");
      setNotices((current) => [
        ...current,
        {
          id: payload.link.id,
          kind: "success",
          message: `${payload.link.title} was retrieved and checked.`,
        },
      ]);
    } catch (error) {
      setNotices((current) => [
        ...current,
        {
          id: `link-${Date.now()}`,
          kind: "failure",
          message:
            error instanceof Error
              ? error.message
              : "The public link could not be checked.",
        },
      ]);
    } finally {
      setIsAddingLink(false);
    }
  }

  async function resourceAction(
    resource: ResourceReadiness,
    action: "approve" | "replacement" | "remove" | "retry",
  ) {
    setActiveAction(resource.id);
    try {
      const path =
        action === "remove"
          ? `/api/v1/resources/${resource.id}`
          : action === "retry"
            ? `/api/v1/resources/${resource.id}/process`
            : `/api/v1/resources/${resource.id}/${action}`;
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: action === "remove" ? "DELETE" : "POST",
      });
      const payload = await readApiResponse<ResourceResponse>(response);
      if (action === "remove") {
        setResources((current) =>
          current.filter((item) => item.id !== resource.id),
        );
      } else {
        upsertResource(payload.resource);
      }
      if (action === "replacement") inputRef.current?.click();
    } catch (error) {
      setNotices((current) => [
        ...current,
        {
          id: `${resource.id}-${action}`,
          kind: "failure",
          message:
            error instanceof Error
              ? error.message
              : "The resource action failed.",
        },
      ]);
    } finally {
      setActiveAction(null);
    }
  }

  async function linkAction(
    link: LinkReadiness,
    action: "approve" | "remove" | "retry",
  ) {
    setActiveAction(link.id);
    try {
      const path =
        action === "remove"
          ? `/api/v1/links/${link.id}`
          : action === "retry"
            ? `/api/v1/links/${link.id}/process`
            : `/api/v1/links/${link.id}/approve`;
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: action === "remove" ? "DELETE" : "POST",
      });
      const payload = await readApiResponse<LinkResponse>(response);
      if (action === "remove") {
        setLinks((current) => current.filter((item) => item.id !== link.id));
      } else {
        upsertLink(payload.link);
      }
    } catch (error) {
      setNotices((current) => [
        ...current,
        {
          id: `${link.id}-${action}`,
          kind: "failure",
          message:
            error instanceof Error ? error.message : "The link action failed.",
        },
      ]);
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <div className="readiness-workspace">
      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="file-picker">
          <label htmlFor="backlog-files">
            <span className="picker-icon" aria-hidden="true">
              +
            </span>
            <strong>Choose learning resources</strong>
            <span>PDF, PNG, JPG, WebP, TXT, MD, SRT, VTT, or ZIP</span>
            <span>Maximum 25 MB per file</span>
          </label>
          <input
            ref={inputRef}
            id="backlog-files"
            name="files"
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.srt,.vtt,.zip"
            multiple
            disabled={isUploading}
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
              setNotices([]);
            }}
          />
        </div>

        {files.length > 0 && (
          <section className="selected-files" aria-labelledby="selected-title">
            <div className="upload-section-heading">
              <h2 id="selected-title">Selected resources</h2>
              <button
                type="button"
                onClick={() => {
                  setFiles([]);
                  if (inputRef.current) inputRef.current.value = "";
                }}
                disabled={isUploading}
              >
                Clear
              </button>
            </div>
            <ul>
              {files.map((file, index) => (
                <li key={`${file.name}-${file.lastModified}-${index}`}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{file.name}</strong>
                    <small>{formatBytes(file.size)}</small>
                  </div>
                  <span>
                    {activeFile === index ? "Checking" : "Queued"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {invalidSelection && (
          <p className="upload-alert" role="alert">
            {invalidSelection.name} is larger than 25 MB.
          </p>
        )}

        <button
          className="upload-submit"
          type="submit"
          disabled={
            !files.length ||
            Boolean(invalidSelection) ||
            isUploading ||
            !projectId
          }
        >
          {isUploading
            ? `Checking ${activeFile + 1} of ${files.length}...`
            : `Upload and check ${files.length || ""} resource${
                files.length === 1 ? "" : "s"
              }`}
        </button>

        {notices.length > 0 && (
          <div className="resource-notices" aria-live="polite">
            {notices.map((notice) => (
              <p key={notice.id} className={`notice-${notice.kind}`}>
                {notice.message}
              </p>
            ))}
          </div>
        )}
      </form>

      <form className="link-intake" onSubmit={handleLinkSubmit}>
        <div>
          <label htmlFor="learning-link">Add a public learning link</label>
          <p>
            YouTube, GitHub, coding sheets, documentation, and public coding
            resources.
          </p>
        </div>
        <div className="link-input-row">
          <input
            id="learning-link"
            type="url"
            value={linkUrl}
            placeholder="https://..."
            required
            disabled={isAddingLink}
            onChange={(event) => setLinkUrl(event.target.value)}
          />
          <button
            type="submit"
            disabled={!projectId || !linkUrl.trim() || isAddingLink}
          >
            {isAddingLink ? "Checking..." : "Add link"}
          </button>
        </div>
      </form>

      <section className="readiness-panel" aria-labelledby="readiness-title">
        <div className="readiness-heading">
          <div>
            <p className="section-kicker">Resource readiness</p>
            <h2 id="readiness-title">Know what can move forward.</h2>
          </div>
          <span>{resources.length + links.length} checked</span>
        </div>

        {resources.length + links.length === 0 ? (
          <div className="readiness-empty">
            <strong>Your readiness list will appear here.</strong>
            <p>
              Each resource gets a clear result and a suggested next step.
            </p>
          </div>
        ) : (
          <div className="readiness-list" aria-live="polite">
            {resources.map((resource) => (
              <article
                className={`readiness-card ${toneFor(resource)}`}
                key={resource.id}
              >
                <header>
                  <div>
                    <p>
                      {resource.content_type} · {formatBytes(resource.size_bytes)}
                    </p>
                    <h3>{resource.filename}</h3>
                  </div>
                  <span className="readiness-badge">
                    {activeAction === resource.id
                      ? "Processing"
                      : formatStatus(resource)}
                  </span>
                </header>

                <p className="readiness-explanation">
                  {resource.explanation ||
                    "Uploaded — waiting for readiness processing."}
                </p>

                <dl className="readiness-metrics">
                  <div>
                    <dt>Confidence</dt>
                    <dd>
                      {resource.confidence === null
                        ? "Not scored"
                        : `${Math.round(resource.confidence * 100)}%`}
                    </dd>
                  </div>
                  <div>
                    <dt>Extracted</dt>
                    <dd>
                      {resource.extracted_page_count !== null
                        ? `${resource.extracted_page_count}/${
                            resource.total_page_count ?? "?"
                          } pages`
                        : `${resource.extracted_character_count.toLocaleString()} chars`}
                    </dd>
                  </div>
                  <div>
                    <dt>Language</dt>
                    <dd>{resource.detected_language || "Unknown"}</dd>
                  </div>
                </dl>

                {resource.content_summary && (
                  <p className="content-summary">{resource.content_summary}</p>
                )}

                <div className="resource-actions">
                  {(resource.readiness_status === "duplicate" ||
                    resource.readiness_status === "irrelevant") &&
                    !resource.approved && (
                      <button
                        type="button"
                        onClick={() => void resourceAction(resource, "approve")}
                        disabled={activeAction === resource.id}
                      >
                        Include Anyway
                      </button>
                    )}
                  {resource.readiness_status !== "ready" && (
                    <button
                      type="button"
                      onClick={() => void resourceAction(resource, "retry")}
                      disabled={activeAction === resource.id}
                    >
                      Retry Processing
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      void resourceAction(resource, "replacement")
                    }
                    disabled={activeAction === resource.id}
                  >
                    Replace
                  </button>
                  <button
                    type="button"
                    onClick={() => void resourceAction(resource, "remove")}
                    disabled={activeAction === resource.id}
                  >
                    Remove
                  </button>
                  <button
                    type="button"
                    aria-expanded={detailsId === resource.id}
                    onClick={() =>
                      setDetailsId((current) =>
                        current === resource.id ? null : resource.id,
                      )
                    }
                  >
                    View Details
                  </button>
                </div>

                {detailsId === resource.id && (
                  <div className="readiness-details">
                    <strong>Why ZeroBacklog chose this status</strong>
                    <p>{resource.technical_reason || "Processing is pending."}</p>
                    {resource.duplicate_match && (
                      <p>
                        Match: {resource.duplicate_match.filename} (
                        {Math.round(resource.duplicate_match.similarity * 100)}%
                        , {resource.duplicate_match.kind})
                      </p>
                    )}
                    <p>
                      Suggested action:{" "}
                      {resource.suggested_action || "Wait for processing."}
                    </p>
                  </div>
                )}
              </article>
            ))}
            {links.map((link) => (
              <article
                className={`readiness-card ${toneForLink(link)}`}
                key={link.id}
              >
                <header>
                  <div>
                    <p>
                      {link.source_type.replaceAll("_", " ")} · public link
                    </p>
                    <h3>{link.title}</h3>
                  </div>
                  <span className="readiness-badge">
                    {activeAction === link.id
                      ? "Processing"
                      : link.approved
                        ? "Included"
                        : link.status.replace("_", " ")}
                  </span>
                </header>

                <p className="readiness-explanation">{link.explanation}</p>
                {link.source_type === "youtube" && (
                  <div className="youtube-transparency">
                    <strong>Metadata only</strong>
                    <p>
                      Metadata processed. Spoken video content was not analyzed
                      because no transcript was available.
                    </p>
                    <small>
                      Have a transcript? Upload it as TXT, SRT, or VTT alongside
                      this link.
                    </small>
                  </div>
                )}

                <dl className="readiness-metrics">
                  <div>
                    <dt>Confidence</dt>
                    <dd>
                      {link.confidence === null
                        ? "Not scored"
                        : `${Math.round(link.confidence * 100)}%`}
                    </dd>
                  </div>
                  <div>
                    <dt>Retrieved</dt>
                    <dd>
                      {link.extracted_character_count.toLocaleString()} chars
                    </dd>
                  </div>
                  <div>
                    <dt>Duration</dt>
                    <dd>
                      {link.duration_seconds === null
                        ? "Unknown"
                        : `${Math.ceil(link.duration_seconds / 60)} min`}
                    </dd>
                  </div>
                </dl>

                {link.content_summary && (
                  <p className="content-summary">{link.content_summary}</p>
                )}

                <div className="resource-actions">
                  {(link.status === "partial" ||
                    link.status === "irrelevant") &&
                    !link.approved && (
                      <button
                        type="button"
                        onClick={() => void linkAction(link, "approve")}
                        disabled={activeAction === link.id}
                      >
                        Include Anyway
                      </button>
                    )}
                  {link.status !== "ready" && (
                    <button
                      type="button"
                      onClick={() => void linkAction(link, "retry")}
                      disabled={activeAction === link.id}
                    >
                      Retry Processing
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void linkAction(link, "remove")}
                    disabled={activeAction === link.id}
                  >
                    Remove
                  </button>
                  <button
                    type="button"
                    aria-expanded={detailsId === link.id}
                    onClick={() =>
                      setDetailsId((current) =>
                        current === link.id ? null : link.id,
                      )
                    }
                  >
                    View Details
                  </button>
                </div>

                {detailsId === link.id && (
                  <div className="readiness-details">
                    <strong>Why ZeroBacklog chose this status</strong>
                    <p>{link.technical_reason}</p>
                    <p>
                      Source:{" "}
                      <a href={link.url} rel="noreferrer" target="_blank">
                        Open public link
                      </a>
                    </p>
                    {link.source_type === "youtube" && (
                      <p>
                        The title, description, channel, duration, and public
                        description links were processed. No timestamps or
                        spoken claims were inferred.
                      </p>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}

        <button
          className="continue-button"
          type="button"
          disabled={eligibleCount < 2 || !projectId}
          onClick={() => router.push(`/results?project_id=${projectId}`)}
        >
          Continue with {eligibleCount} ready resource
          {eligibleCount === 1 ? "" : "s"}
        </button>
        {eligibleCount < 2 && (
          <p className="continuation-note">
            Add at least two ready or approved resources to compare.
          </p>
        )}
      </section>
    </div>
  );
}
