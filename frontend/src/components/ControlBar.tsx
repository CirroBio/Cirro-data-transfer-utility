import { useRef, useState } from "react";
import { api } from "../api";
import type { Project } from "../types";

interface Props {
  connected: boolean;
  projects: Project[];
  defaultProject: string;
  onDefaultProject: (id: string) => void;
  onChanged: () => void;
  onError: (msg: string) => void;
}

export default function ControlBar({
  connected,
  projects,
  defaultProject,
  onDefaultProject,
  onChanged,
  onError,
}: Props) {
  const datasetsRef = useRef<HTMLInputElement>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function guard(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadCsv() {
    const d = datasetsRef.current?.files?.[0];
    const f = filesRef.current?.files?.[0];
    if (!d || !f) {
      onError("Choose both dataset_plan.csv and file_plan.csv.");
      return;
    }
    await guard(() => api.uploadCsv(d, f));
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Controls</h2>
        {!connected && <span className="faint" style={{ fontSize: 12 }}>Log in to reconcile & transfer</span>}
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <label className="field">Fallback project</label>
        <select
          value={defaultProject}
          disabled={!connected}
          title="Used only if a dataset row has no study; normally the study is the project."
          onChange={(e) => {
            onDefaultProject(e.target.value);
            api.setDefaultProject(e.target.value).catch(() => {});
          }}
        >
          <option value="">— none —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div className="row" style={{ marginBottom: 12 }}>
        <label className="field">dataset_plan.csv</label>
        <input ref={datasetsRef} type="file" accept=".csv" />
        <label className="field">file_plan.csv</label>
        <input ref={filesRef} type="file" accept=".csv" />
        <button className="secondary" onClick={loadCsv} disabled={busy}>
          Load plan
        </button>
      </div>

      <div className="row">
        <button disabled={!connected || busy} onClick={() => guard(() => api.reconcile(defaultProject || null))}>
          Reconcile
        </button>
        <button disabled={!connected || busy} onClick={() => guard(() => api.transferAll())}>
          Transfer all pending
        </button>
        <button className="secondary" disabled={!connected || busy} onClick={() => guard(() => api.retryFailed())}>
          Retry failed
        </button>
      </div>
    </div>
  );
}
