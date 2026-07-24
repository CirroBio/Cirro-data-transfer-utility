import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeEvents } from "./api";
import AuthPanel from "./components/AuthPanel";
import ControlBar from "./components/ControlBar";
import DatasetTable from "./components/DatasetTable";
import ExcludedPanel from "./components/ExcludedPanel";
import QueuePanel from "./components/QueuePanel";
import type { AuthStatus, Dataset, ExcludedDataset, Project, QueueItem, SseEvent } from "./types";

function humanBytes(n: number): string {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i > 0 ? 1 : 0)} ${u[i]}`;
}

function progressText(e: SseEvent): string | null {
  if (e.type !== "progress") return null;
  if (e.phase === "download") {
    const of = e.total ? ` / ${humanBytes(e.total)}` : "";
    return `⬇ ${e.file} — ${humanBytes(e.bytes ?? 0)}${of}`;
  }
  if (e.resume) return "⬆ resuming upload…";
  return `⬆ uploading ${e.done ?? 0}/${e.total ?? 0}${e.file ? ` — ${e.file}` : ""}`;
}

export default function App() {
  const [auth, setAuth] = useState<AuthStatus>({
    status: "disconnected",
    user: null,
    auth_message: null,
    base_url: "",
    error: null,
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [excluded, setExcluded] = useState<ExcludedDataset[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [defaultProject, setDefaultProject] = useState("");
  const [progress, setProgress] = useState<Record<string, string>>({});
  const [checksumMethod, setChecksumMethod] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connected = auth.status === "connected";
  const refreshTimer = useRef<number | null>(null);

  const refreshData = useCallback(() => {
    api.datasets().then(setDatasets).catch(() => {});
    api.excluded().then(setExcluded).catch(() => {});
    api.queue().then(setQueue).catch(() => {});
  }, []);

  // Debounce bursts of SSE-triggered refreshes.
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(refreshData, 300);
  }, [refreshData]);

  // Poll auth status until connected (covers the device-code wait).
  useEffect(() => {
    let active = true;
    const tick = () =>
      api.authStatus().then((s) => {
        if (active) setAuth(s);
      });
    tick();
    const id = window.setInterval(() => {
      if (auth.status !== "connected") tick();
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [auth.status]);

  // Load persisted datasets/queue on mount (they survive restarts and don't
  // require a Cirro connection to display).
  useEffect(() => {
    refreshData();
  }, [refreshData]);

  // On connect, load projects (which do require auth).
  useEffect(() => {
    if (connected) {
      api.projects().then(setProjects).catch(() => {});
      refreshData();
    }
  }, [connected, refreshData]);

  // Subscribe to the server event stream once.
  useEffect(() => {
    return subscribeEvents((e) => {
      const text = progressText(e);
      if (text && "key" in e) {
        setProgress((p) => ({ ...p, [e.key]: text }));
      }
      if (e.type === "dataset") {
        if (e.checksum_method) setChecksumMethod(e.checksum_method);
        if (["DONE", "FAILED", "PRESENT"].includes(e.status)) {
          setProgress((p) => {
            const { [e.key]: _drop, ...rest } = p;
            return rest;
          });
        }
        scheduleRefresh();
      }
      if (e.type === "queue") scheduleRefresh();
      if (e.type === "warning") setError(`${e.name}: ${e.message}`);
    });
  }, [scheduleRefresh]);

  return (
    <>
      <header>
        <div className="logo" aria-hidden>⇪</div>
        <div>
          <h1>Cirro Data Transfer Utility</h1>
          <div className="subtitle">bulk-load external files into Cirro as datasets</div>
        </div>
      </header>

      <div className="container">
        {error && (
          <div className="stack" style={{ paddingBottom: 0 }}>
            <div className="alert">
              <span>{error}</span>
              <div className="spacer" />
              <button className="secondary" onClick={() => setError(null)}>Dismiss</button>
            </div>
          </div>
        )}

        <div className="stack">
          <AuthPanel auth={auth} onLogin={() => api.login().then(setAuth).catch((e) => setError(String(e)))} />
        </div>

        <div className="layout">
          <div>
            <ControlBar
              connected={connected}
              projects={projects}
              defaultProject={defaultProject}
              onDefaultProject={setDefaultProject}
              onChanged={refreshData}
              onError={setError}
            />
            <DatasetTable
              datasets={datasets}
              progress={progress}
              connected={connected}
              onChanged={refreshData}
            />
            <ExcludedPanel excluded={excluded} />
          </div>
          <div>
            <QueuePanel queue={queue} progress={progress} checksumMethod={checksumMethod} />
          </div>
        </div>
      </div>
    </>
  );
}
