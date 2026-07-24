import type { AuthStatus, Dataset, ExcludedDataset, Project, QueueItem, SseEvent } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  authStatus: () => fetch("/auth/status").then(json<AuthStatus>),
  login: () => fetch("/auth/login", { method: "POST" }).then(json<AuthStatus>),
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
  retryFailed: () =>
    fetch("/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(json),
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
