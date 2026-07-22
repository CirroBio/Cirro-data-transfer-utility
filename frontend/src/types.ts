export interface AuthStatus {
  status: "disconnected" | "pending" | "connected" | "error";
  user: string | null;
  auth_message: string | null;
  base_url: string;
  error: string | null;
}

export interface Project {
  id: string;
  name: string;
}

export interface FileRow {
  relative_path: string;
  source_uri: string;
  expected_size: number | null;
  status: string;
  verify_tier: string | null;
  downloaded_bytes: number;
}

export interface Dataset {
  name: string;
  project: string | null;
  data_type: string;
  description: string;
  folder_path: string | null;
  tags: string[];
  status: string;
  error: string | null;
  dataset_id: string | null;
  files: FileRow[];
}

export interface QueueItem {
  dataset_name: string;
  state: string;
  enqueued_at: string;
}

export type SseEvent =
  | { type: "dataset"; name: string; status: string; error?: string; dataset_id?: string; checksum_method?: string }
  | { type: "progress"; name: string; phase: "download" | "upload"; file?: string; bytes?: number; total?: number | null; done?: number; resume?: boolean }
  | { type: "queue"; action: string; names: string[] }
  | { type: "warning"; name: string; message: string };
