"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/config";
import type {
  ApiErrorResponse,
  UploadMetadata,
  UploadResponse,
} from "@/types/upload";

type UploadResult =
  | { filename: string; kind: "success"; upload: UploadMetadata }
  | { filename: string; kind: "failure"; message: string };

const MAX_FILE_SIZE = 25 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadForm() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [activeFile, setActiveFile] = useState<number | null>(null);

  const invalidSelection = useMemo(
    () => files.find((file) => file.size > MAX_FILE_SIZE),
    [files],
  );
  const isUploading = activeFile !== null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length || invalidSelection || isUploading) return;

    setResults([]);
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      setActiveFile(index);
      const formData = new FormData();
      formData.append("file", file);

      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/uploads`, {
          method: "POST",
          body: formData,
        });
        const payload: UploadResponse | ApiErrorResponse = await response.json();

        if (!response.ok || !("upload" in payload)) {
          const message =
            "error" in payload && payload.error?.message
              ? payload.error.message
              : "The upload could not be completed.";
          setResults((current) => [
            ...current,
            { filename: file.name, kind: "failure", message },
          ]);
          continue;
        }

        setResults((current) => [
          ...current,
          { filename: file.name, kind: "success", upload: payload.upload },
        ]);
      } catch {
        setResults((current) => [
          ...current,
          {
            filename: file.name,
            kind: "failure",
            message: "The API is unavailable. Start the backend and retry.",
          },
        ]);
      }
    }

    setActiveFile(null);
  }

  function resetForm() {
    setFiles([]);
    setResults([]);
    setActiveFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <div className="file-picker">
        <label htmlFor="backlog-files">
          <span className="picker-icon" aria-hidden="true">+</span>
          <strong>Choose learning resources</strong>
          <span>PDF, PNG, JPG, WebP, GIF, TXT, MD, CSV, JSON, or ZIP</span>
          <span>Maximum 25 MB per file</span>
        </label>
        <input
          ref={inputRef}
          id="backlog-files"
          name="files"
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv,.json,.zip"
          multiple
          disabled={isUploading}
          onChange={(event) => {
            setFiles(Array.from(event.target.files ?? []));
            setResults([]);
          }}
        />
      </div>

      {files.length > 0 && (
        <section className="selected-files" aria-labelledby="selected-title">
          <div className="upload-section-heading">
            <h2 id="selected-title">Selected resources</h2>
            <button type="button" onClick={resetForm} disabled={isUploading}>
              Clear
            </button>
          </div>
          <ul>
            {files.map((file, index) => (
              <li key={`${file.name}-${file.lastModified}`}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{file.name}</strong>
                  <small>{formatBytes(file.size)}</small>
                </div>
                <span>
                  {activeFile === index ? "Uploading" : "Ready"}
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
        disabled={!files.length || Boolean(invalidSelection) || isUploading}
      >
        {isUploading
          ? `Storing ${activeFile + 1} of ${files.length}…`
          : `Store ${files.length || ""} resource${files.length === 1 ? "" : "s"}`}
      </button>

      {results.length > 0 && (
        <section className="upload-results" aria-labelledby="results-title">
          <div className="upload-section-heading">
            <h2 id="results-title">Upload results</h2>
          </div>
          <ul aria-live="polite">
            {results.map((result) => (
              <li
                key={`${result.filename}-${result.kind}`}
                className={result.kind === "success" ? "result-success" : "result-failure"}
              >
                <span aria-hidden="true">
                  {result.kind === "success" ? "✓" : "!"}
                </span>
                <div>
                  <strong>{result.filename}</strong>
                  {result.kind === "success" ? (
                    <>
                      <p>Stored in B2 and recorded in Neon.</p>
                      <code>{result.upload.id}</code>
                    </>
                  ) : (
                    <p>{result.message}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </form>
  );
}
