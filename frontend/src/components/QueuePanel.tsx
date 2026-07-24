import type { QueueItem } from "../types";

interface Props {
  queue: QueueItem[];
  progress: Record<string, string>;
  checksumMethod: string | null;
}

export default function QueuePanel({ queue, progress, checksumMethod }: Props) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Transfer Queue</h2>
        <span className="count">{queue.length}</span>
      </div>
      {checksumMethod && (
        <p className="faint" style={{ fontSize: 12, marginTop: 0 }}>
          Uploads verified with {checksumMethod} checksums.
        </p>
      )}
      {queue.length === 0 && (
        <div className="empty">
          <span className="icon">🗂️</span>
          Queue is empty.
        </div>
      )}
      {queue.map((q) => {
        const running = q.state === "RUNNING";
        return (
          <div key={q.dataset_key} className="queue-card">
            <div className="row">
              <strong>{q.name || q.dataset_key}</strong>
              <div className="spacer" />
              <span className={`badge ${running ? "RUNNING" : "PENDING"}`}>{q.state}</span>
            </div>
            {progress[q.dataset_key] && <div className="progress">{progress[q.dataset_key]}</div>}
            {running && (
              <div className="bar indeterminate">
                <span />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
