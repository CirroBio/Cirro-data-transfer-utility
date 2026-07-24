import { useState } from "react";
import type { ExcludedDataset } from "../types";

interface Props {
  excluded: ExcludedDataset[];
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

export default function ExcludedPanel({ excluded }: Props) {
  const [open, setOpen] = useState(false);
  if (excluded.length === 0) return null;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Excluded by plan</h2>
        <span className="count">{excluded.length}</span>
        <div className="spacer" />
        <button className="secondary" onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <table>
          <thead>
            <tr>
              <th>Source dataset</th>
              <th>Study</th>
              <th>Files</th>
              <th>Size</th>
              <th>Excluded at</th>
            </tr>
          </thead>
          <tbody>
            {excluded.map((e) => (
              <tr key={`${e.study}/${e.source_dataset_id}`}>
                <td className="mono">{e.source_dataset_id}</td>
                <td className="muted">{e.study}</td>
                <td>{e.n_files ?? "—"}</td>
                <td>{humanBytes(e.total_size_bytes)}</td>
                <td className="muted">{e.excluded_at || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
