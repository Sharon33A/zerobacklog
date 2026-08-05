export interface UploadMetadata {
  id: string;
  project_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  status: "stored";
  bucket: string;
  object_key: string;
  created_at: string;
}

export interface UploadResponse {
  upload: UploadMetadata;
}

export interface ApiErrorResponse {
  error?: {
    code?: string;
    message?: string;
  };
}

export type ReadinessStatus =
  | "ready"
  | "partial"
  | "low_confidence"
  | "irrelevant"
  | "duplicate"
  | "unreadable"
  | "unsupported"
  | "failed";

export interface DuplicateReference {
  resource_id: string;
  filename: string;
  kind: "exact" | "near";
  similarity: number;
}

export interface ResourceReadiness {
  id: string;
  project_id: string;
  source_kind: "file";
  filename: string;
  content_type: string;
  size_bytes: number;
  lifecycle_state: string;
  readiness_status: ReadinessStatus | null;
  explanation: string | null;
  technical_reason: string | null;
  confidence: number | null;
  extracted_character_count: number;
  extracted_page_count: number | null;
  total_page_count: number | null;
  detected_language: string | null;
  duplicate_match: DuplicateReference | null;
  suggested_action: string | null;
  content_summary: string | null;
  extracted_object_key: string | null;
  metadata_object_key: string | null;
  approved: boolean;
  marked_for_replacement: boolean;
  removed: boolean;
  eligible_for_analysis: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResourceResponse {
  resource: ResourceReadiness;
}

export interface ResourceListResponse {
  project_id: string;
  resources: ResourceReadiness[];
  links: LinkReadiness[];
  eligible_count: number;
}

export type LinkStatus =
  | "processing"
  | "ready"
  | "partial"
  | "inaccessible"
  | "irrelevant"
  | "failed";

export interface LinkReadiness {
  id: string;
  project_id: string;
  source_kind: "link";
  url: string;
  source_type: string;
  title: string;
  description: string | null;
  author: string | null;
  duration_seconds: number | null;
  outbound_links: string[];
  status: LinkStatus;
  explanation: string;
  technical_reason: string;
  confidence: number | null;
  extracted_character_count: number;
  snapshot_object_key: string | null;
  metadata_object_key: string | null;
  content_summary: string | null;
  approved: boolean;
  removed: boolean;
  eligible_for_analysis: boolean;
  created_at: string;
  updated_at: string;
}

export interface LinkResponse {
  link: LinkReadiness;
}
