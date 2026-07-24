import { Fragment, useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

interface Props {
  datasets: Dataset[];
  progress: Record<string, string>;
  connected: boolean;
  onChanged: () => void;
}

// cirro_folder_path is rooted at the study (= project); the in-project folder
// is that path with the study prefix removed.
function folderInProject(study: string, folderPath: string): string {
  if (folderPath === study) return "";
  return folderPath.startsWith(study + "/") ? folderPath.slice(study.length + 1) : folderPath;
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
          No datasets loaded. Choose your <strong>dataset_plan.csv</strong> and{" "}
          <strong>file_plan.csv</strong> above, then <strong>Load plan</strong>.
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
            <th>Project (study)</th>
            <th>Folder</th>
            <th>Data type</th>
            <th>Files</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => {
            const folder = folderInProject(d.study, d.folder_path);
            return (
            <Fragment key={d.key}>
              <tr>
                <td>
                  <span className="name">{d.name}</span>
                </td>
                <td className="muted">{d.study || "—"}</td>
                <td className="muted mono">{folder || "/"}</td>
                <td className="muted" title={d.data_type}>{d.cirro_type_name || d.data_type}</td>
                <td>
                  {d.files.length}
                  {d.planned_files != null && d.planned_files !== d.files.length && (
                    <span className="faint"> / {d.planned_files}</span>
                  )}
                </td>
                <td>
                  <span className={`badge ${d.status}`}>{d.status}</span>
                  {progress[d.key] && <div className="progress">{progress[d.key]}</div>}
                  {d.error && <div className="error" style={{ fontSize: 12 }}>{d.error}</div>}
                </td>
                <td className="row">
                  <button
                    className="secondary"
                    onClick={() => setExpanded(expanded === d.key ? null : d.key)}
                  >
                    {expanded === d.key ? "Hide" : "Files"}
                  </button>
                  {connected && ["PENDING", "MISMATCH", "FAILED"].includes(d.status) && (
                    <button onClick={() => api.transfer([d.key]).then(onChanged)}>Transfer</button>
                  )}
                </td>
              </tr>
              {expanded === d.key && (
                <tr>
                  <td colSpan={7}>
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
