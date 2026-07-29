import type {
  AuthStatus,
  CredentialsStatus,
  Dataset,
  ExcludedDataset,
  Project,
  QueueItem,
  SseEvent,
} from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    // Name the request: a bare "Not Found" gives no clue which call failed, and
    // a 404 on a route the server predates is the usual cause.
    const path = new URL(res.url).pathname;
    throw new Error(`${path} — ${res.status} ${message}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authStatus: () => fetch("/auth/status").then(json<AuthStatus>),
  login: () => fetch("/auth/login", { method: "POST" }).then(json<AuthStatus>),
  logout: () => fetch("/auth/logout", { method: "POST" }).then(json<AuthStatus>),
  setBaseUrl: (baseUrl: string) =>
    fetch("/auth/base-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl }),
    }).then(json<AuthStatus>),
  credentials: () => fetch("/credentials").then(json<CredentialsStatus>),
  setAwsCredentials: (body: {
    access_key_id: string;
    secret_access_key: string;
    session_token?: string;
    region?: string;
  }) =>
    fetch("/credentials/aws", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<CredentialsStatus>),
  setGcpCredentials: (serviceAccountJson: string) =>
    fetch("/credentials/gcp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service_account_json: serviceAccountJson }),
    }).then(json<CredentialsStatus>),
  clearCredentials: (provider: "aws" | "gcp") =>
    fetch(`/credentials/${provider}`, { method: "DELETE" }).then(json<CredentialsStatus>),
  projects: () => fetch("/projects").then(json<Project[]>),
  datasets: () => fetch("/datasets").then(json<Dataset[]>),
  excluded: () => fetch("/excluded").then(json<ExcludedDataset[]>),
  queue: () => fetch("/queue").then(json<QueueItem[]>),
  setDefaultProject: (project: string) =>
    fetch("/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ default_project: project }),
    }).then(json),
  reconcile: (defaultProject: string | null) =>
    fetch("/reconcile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ default_project: defaultProject }),
    }).then(json),
  transferAll: () =>
    fetch("/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ all: true }),
    }).then(json),
  transfer: (keys: string[]) =>
    fetch("/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    }).then(json),
  cancel: (keys: string[]) =>
    fetch("/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    }).then(json<{ dropped: string[]; stopping: string[] }>),
  cancelAll: () =>
    fetch("/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ all: true }),
    }).then(json<{ dropped: string[]; stopping: string[] }>),
  retryFailed: () =>
    fetch("/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(json),
  clearPlan: () =>
    fetch("/datasets", { method: "DELETE" }).then(
      json<{ cleared: Record<string, number> }>,
    ),
  uploadCsv: (datasetPlan: File, filePlan: File) => {
    const body = new FormData();
    body.append("dataset_plan", datasetPlan);
    body.append("file_plan", filePlan);
    return fetch("/csv", { method: "POST", body }).then(
      json<{ loaded: number; excluded: number; datasets: { key: string; name: string; files: number }[] }>,
    );
  },
};

export function subscribeEvents(onEvent: (e: SseEvent) => void): () => void {
  const source = new EventSource("/events");
  source.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as SseEvent);
    } catch {
      /* keepalive lines */
    }
  };
  return () => source.close();
}
