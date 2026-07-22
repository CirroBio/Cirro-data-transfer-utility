import { Fragment, useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

interface Props {
  datasets: Dataset[];
  progress: Record<string, string>;
  connected: boolean;
  onChanged: () => void;
}

function humanBytes(n: number | null): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export default function DatasetTable({ datasets, progress, connected, onChanged }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (datasets.length === 0) {
    return (
      <div className="panel">
        <div className="panel-head">
          <h2>Datasets</h2>
          <span className="count">0</span>
        </div>
        <div className="empty">
          <span className="icon">📄</span>
          No datasets loaded. Choose your <strong>datasets.csv</strong> and{" "}
          <strong>files.csv</strong> above, then <strong>Load CSVs</strong>.
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Datasets</h2>
        <span className="count">{datasets.length}</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Project</th>
            <th>Data type</th>
            <th>Files</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => (
            <Fragment key={d.name}>
              <tr>
                <td>
                  <span className="name">{d.name}</span>
                  {d.tags.length > 0 && (
                    <div className="tags">
                      {d.tags.map((t) => (
                        <span key={t} className={`tag${t.startsWith("folder://") ? " folder" : ""}`}>{t}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="muted">{d.project || "—"}</td>
                <td className="muted mono">{d.data_type}</td>
                <td>{d.files.length}</td>
                <td>
                  <span className={`badge ${d.status}`}>{d.status}</span>
                  {progress[d.name] && <div className="progress">{progress[d.name]}</div>}
                  {d.error && <div className="error" style={{ fontSize: 12 }}>{d.error}</div>}
                </td>
                <td className="row">
                  <button
                    className="secondary"
                    onClick={() => setExpanded(expanded === d.name ? null : d.name)}
                  >
                    {expanded === d.name ? "Hide" : "Files"}
                  </button>
                  {connected && ["PENDING", "MISMATCH", "FAILED"].includes(d.status) && (
                    <button onClick={() => api.transfer([d.name]).then(onChanged)}>Transfer</button>
                  )}
                </td>
              </tr>
              {expanded === d.name && (
                <tr>
                  <td colSpan={6}>
                    <table className="files-detail">
                      <thead>
                        <tr>
                          <th>Relative path</th>
                          <th>Source</th>
                          <th>Size</th>
                          <th>State</th>
                          <th>Verified by</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.files.map((f) => (
                          <tr key={f.relative_path}>
                            <td className="mono">{f.relative_path}</td>
                            <td className="muted mono">{f.source_uri}</td>
                            <td>{humanBytes(f.expected_size)}</td>
                            <td>{f.status}</td>
                            <td>
                              {f.verify_tier ? (
                                <span className={`tier ${f.verify_tier}`}>{f.verify_tier}</span>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
