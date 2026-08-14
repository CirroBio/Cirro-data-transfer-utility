import type {
  AppConfig,
  AuthStatus,
  CredentialsStatus,
  Dataset,
  EventPoll,
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
  clearCredentials: (provider: "aws") =>
    fetch(`/credentials/${provider}`, { method: "DELETE" }).then(json<CredentialsStatus>),
  projects: () => fetch("/projects").then(json<Project[]>),
  datasets: () => fetch("/datasets").then(json<Dataset[]>),
  excluded: () => fetch("/excluded").then(json<ExcludedDataset[]>),
  queue: () => fetch("/queue").then(json<QueueItem[]>),
  config: () => fetch("/config").then(json<AppConfig>),
  pollEvents: (since: number | null) =>
    fetch(since === null ? "/events/poll" : `/events/poll?since=${since}`).then(json<EventPoll>),
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

// A stream that has not produced its opening `hello` this quickly is either
// blocked or being buffered by a proxy — neither recovers on its own.
const SSE_HELLO_TIMEOUT_MS = 4000;
// Once running, the server sends a ping every 15s; silence for this long means
// the stream died without an error the browser surfaced.
const SSE_SILENCE_TIMEOUT_MS = 40000;
const POLL_INTERVAL_MS = 1000;

/** Receive progress events, over SSE where it works and short polls where it
 *  doesn't. `onResync` fires when the transport cannot guarantee it saw every
 *  event, and the caller should reload state from the REST endpoints. */
export function subscribeEvents(
  onEvent: (e: SseEvent) => void,
  onResync: () => void,
): () => void {
  let stopped = false;
  let source: EventSource | null = null;
  let timer: number | null = null;
  // Where polling picks up. Null means "start from now", which loses whatever
  // was published while SSE was being tried, hence the resync alongside it.
  let cursor: number | null = null;

  const poll = () => {
    api
      .pollEvents(cursor)
      .then((batch) => {
        cursor = batch.seq;
        if (batch.gap) onResync();
        else batch.events.forEach(onEvent);
      })
      .catch((e) => console.warn("event poll failed, retrying", e))
      .finally(() => {
        if (!stopped) timer = window.setTimeout(poll, POLL_INTERVAL_MS);
      });
  };

  const fallBackToPolling = () => {
    if (stopped) return;
    if (timer) window.clearTimeout(timer);
    source?.close();
    source = null;
    if (cursor === null) onResync();
    poll();
  };

  const connect = (canFallBack: boolean) => {
    source = new EventSource("/events");
    const arm = (ms: number) => {
      if (timer) window.clearTimeout(timer);
      if (canFallBack) timer = window.setTimeout(fallBackToPolling, ms);
    };
    arm(SSE_HELLO_TIMEOUT_MS);
    source.onmessage = (msg) => {
      arm(SSE_SILENCE_TIMEOUT_MS);
      const event = JSON.parse(msg.data) as SseEvent | { type: "hello"; seq: number } | { type: "ping" };
      if (event.type === "hello") cursor = event.seq;
      else if (event.type !== "ping") onEvent(event);
    };
    // Before the first frame an error is fatal; after it, EventSource
    // reconnects on its own and the silence timeout is the real backstop.
    source.onerror = () => {
      if (cursor === null) fallBackToPolling();
    };
  };

  api
    .config()
    .catch(() => ({ events_transport: "auto" }))
    .then(({ events_transport }) => {
      if (stopped) return;
      if (events_transport === "poll") poll();
      else connect(events_transport !== "sse");
    });

  return () => {
    stopped = true;
    if (timer) window.clearTimeout(timer);
    source?.close();
  };
}
