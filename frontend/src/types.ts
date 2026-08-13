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

/** Presence and a non-reversible hint per provider — never the secrets. */
export interface CredentialsStatus {
  aws: {
    configured: boolean;
    hint: string | null;
    temporary: boolean;
    region: string | null;
  };
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

/** Live download progress for one dataset: files completed, plus the file in
 *  flight and its byte counts. */
export interface DownloadProgress {
  done?: number;
  total?: number | null;
  file?: string;
  bytes?: number;
  totalBytes?: number | null;
}

/** Progress through a file-counted phase (upload, verify) — not bytes.
 *  `resume` only appears on uploads. */
export interface FileCountProgress {
  done?: number;
  total?: number | null;
  file?: string;
  resume?: boolean;
}

/** Each phase tracked separately so each gets its own progress bar. */
export interface DatasetProgress {
  download?: DownloadProgress;
  upload?: FileCountProgress;
  verify?: FileCountProgress;
}

export interface QueueItem {
  dataset_key: string;
  name: string | null;
  state: string;
  enqueued_at: string;
}

/** The transfer phases that report progress, in the order they run. */
export type Phase = "download" | "upload" | "verify";

export type SseEvent =
  | { type: "dataset"; key: string; name: string; status: string; error?: string; dataset_id?: string; checksum_method?: string }
  | { type: "progress"; key: string; name: string; phase: Phase; file?: string; bytes?: number; total?: number | null; done?: number; resume?: boolean }
  // One per file as it finishes; carries the running file count for that phase.
  | { type: "file"; key: string; name: string; phase: Phase; file: string; done: number; total: number }
  | { type: "queue"; action: string; keys: string[] }
  | { type: "warning"; key: string; name: string; message: string };
