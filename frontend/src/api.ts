import type { AuthStatus, Dataset, Project, QueueItem, SseEvent } from "./types";

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
  transfer: (names: string[]) =>
    fetch("/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    }).then(json),
  retryFailed: () =>
    fetch("/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(json),
  uploadCsv: (datasetsFile: File, filesFile: File) => {
    const body = new FormData();
    body.append("datasets", datasetsFile);
    body.append("files", filesFile);
    return fetch("/csv", { method: "POST", body }).then(
      json<{ loaded: number; datasets: { name: string; files: number }[] }>,
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
