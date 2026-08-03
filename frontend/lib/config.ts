const configuredApiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/+$/, "");
