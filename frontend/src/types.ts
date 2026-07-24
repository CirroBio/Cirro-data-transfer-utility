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
  key: string;
  name: string;
  study: string;           // the Cirro project
  folder_path: string;     // cirro_folder_path (rooted at study)
  data_type: string;       // cirro_type_id
  cirro_type_name: string;
  source_kind: string | null;
  source_dataset_id: string | null;
  planned_files: number | null;
  planned_bytes: number | null;
  description: string;
  tags: string[];
  status: string;
  error: string | null;
  dataset_id: string | null;
  files: FileRow[];
}

export interface ExcludedDataset {
  study: string;
  source_dataset_id: string;
  source_kind: string | null;
  n_files: number | null;
  total_size_bytes: number | null;
  excluded_at: string | null;
}

export interface QueueItem {
  dataset_key: string;
  name: string | null;
  state: string;
  enqueued_at: string;
}

export type SseEvent =
  | { type: "dataset"; key: string; name: string; status: string; error?: string; dataset_id?: string; checksum_method?: string }
  | { type: "progress"; key: string; name: string; phase: "download" | "upload"; file?: string; bytes?: number; total?: number | null; done?: number; resume?: boolean }
  | { type: "queue"; action: string; keys: string[] }
  | { type: "warning"; key: string; name: string; message: string };
