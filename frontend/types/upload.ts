export interface UploadMetadata {
  id: string;
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
