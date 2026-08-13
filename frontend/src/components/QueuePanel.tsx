import { Box, Button, LinearProgress, Stack, Typography } from "@mui/material";
import { api } from "../api";
import { formatBytes } from "../format";
import type { Dataset, DatasetProgress, QueueItem } from "../types";
import { COLOR_BORDER, COLOR_GRAY, COLOR_MUTED, COLOR_SECONDARY, FONT_MONO } from "../theme";
import Panel from "./Panel";
import StatusChip from "./StatusChip";

interface Props {
  queue: QueueItem[];
  datasets: Dataset[];
  progress: Record<string, DatasetProgress>;
  checksumMethod: string | null;
  onChanged: () => void;
  onError: (msg: string) => void;
}

const mono = { fontFamily: FONT_MONO, fontSize: 12 };

interface BarProps {
  label: string;
  done: number;
  total: number;
  /** Shown under the bar — the file in flight, with byte counts for downloads. */
  detail?: string;
  /** True while this phase is the one running, so a 0-total bar can animate. */
  active: boolean;
}

function PhaseBar({ label, done, total, detail, active }: BarProps) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <Box sx={{ mt: 1.5 }}>
      <Stack direction="row" alignItems="baseline" spacing={1.5} sx={{ mb: 0.5 }}>
        <Typography
          variant="body2"
          sx={{
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            fontSize: 10.5,
            minWidth: 64,
            color: active ? COLOR_SECONDARY : COLOR_MUTED,
          }}
        >
          {label}
        </Typography>
        <Typography sx={mono}>
          {done} / {total} files
        </Typography>
        <Typography variant="body2">{pct}%</Typography>
      </Stack>
      {/* White track: the card background is COLOR_GRAY, so the theme's default
          grey track would make an empty bar invisible. */}
      <LinearProgress
        variant={total > 0 ? "determinate" : active ? "indeterminate" : "determinate"}
        value={total > 0 ? pct : 0}
        sx={{ bgcolor: "#fff", border: `1px solid ${COLOR_BORDER}` }}
      />
      {detail && (
        <Typography sx={{ ...mono, color: COLOR_SECONDARY, mt: 0.5 }} noWrap>
          {detail}
        </Typography>
      )}
    </Box>
  );
}

function downloadDetail(download: DatasetProgress["download"]): string | undefined {
  if (!download?.file) return undefined;
  const totalSuffix = download.totalBytes ? ` / ${formatBytes(download.totalBytes)}` : "";
  return `${download.file} — ${formatBytes(download.bytes ?? 0)}${totalSuffix}`;
}

export default function QueuePanel({
  queue,
  datasets,
  progress,
  checksumMethod,
  onChanged,
  onError,
}: Props) {
  const byKey = new Map(datasets.map((d) => [d.key, d]));

  const stop = (keys: string[]) =>
    api
      .cancel(keys)
      .then(onChanged)
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));

  return (
    <Panel
      title="Transfer Queue"
      count={queue.length}
      subtitle={checksumMethod ? `Uploads verified with ${checksumMethod} checksums.` : undefined}
      actions={
        queue.length > 0 ? (
          <Button
            size="small"
            variant="outlined"
            color="error"
            onClick={() => stop(queue.map((q) => q.dataset_key))}
          >
            Stop all
          </Button>
        ) : undefined
      }
    >
      <Box sx={{ px: 3, py: 2.5 }}>
        {queue.length === 0 && (
          <Typography variant="body2" align="center" sx={{ py: 3 }}>
            Queue is empty.
          </Typography>
        )}
        {queue.map((q) => {
          const dataset = byKey.get(q.dataset_key);
          const phases = progress[q.dataset_key] ?? {};
          const totalFiles = dataset?.files.length ?? 0;

          // Live per-file events are authoritative while a transfer runs; the
          // files table is the fallback after a reload (or before any event).
          const downloadedFromDb = dataset?.files.filter((f) => f.status === "DONE").length ?? 0;
          const downloaded = phases.download?.done ?? downloadedFromDb;
          const downloadTotal = phases.download?.total ?? totalFiles;
          const uploaded = phases.upload?.done ?? 0;
          const uploadTotal = phases.upload?.total ?? totalFiles;
          const verified = phases.verify?.done ?? 0;
          const verifyTotal = phases.verify?.total ?? totalFiles;

          // Only the latest phase reached is the active one.
          const verifying = phases.verify !== undefined;
          const uploading = phases.upload !== undefined && !verifying;
          const downloading = phases.download !== undefined && !uploading && !verifying;

          return (
            <Box
              key={q.dataset_key}
              sx={{
                bgcolor: COLOR_GRAY,
                border: `1px solid ${COLOR_BORDER}`,
                borderRadius: "10px",
                p: 2,
                mb: 1.5,
                "&:last-of-type": { mb: 0 },
              }}
            >
              <Stack direction="row" alignItems="center" spacing={1}>
                <Typography variant="body1" sx={{ fontWeight: 600 }}>
                  {q.name || q.dataset_key}
                </Typography>
                <Box sx={{ flex: 1 }} />
                {dataset && <StatusChip status={dataset.status} />}
                <StatusChip status={q.state} />
                <Button
                  size="small"
                  variant="outlined"
                  color="error"
                  title={
                    q.state === "RUNNING"
                      ? "Stops after the file in flight finishes"
                      : "Removes it from the queue before it starts"
                  }
                  onClick={() => stop([q.dataset_key])}
                >
                  Stop
                </Button>
              </Stack>

              <PhaseBar
                label="Download"
                done={downloaded}
                total={downloadTotal}
                detail={downloadDetail(phases.download)}
                active={downloading}
              />
              <PhaseBar
                label="Upload"
                done={uploaded}
                total={uploadTotal}
                detail={
                  phases.upload?.resume
                    ? "resuming upload…"
                    : phases.upload?.file
                      ? phases.upload.file
                      : undefined
                }
                active={uploading}
              />
              <PhaseBar
                label="Verify"
                done={verified}
                total={verifyTotal}
                detail={phases.verify?.file ?? (verifying ? "waiting for ingest…" : undefined)}
                active={verifying}
              />

              {!dataset && (
                <Typography variant="body2" sx={{ color: COLOR_MUTED, mt: 1 }}>
                  Dataset row not loaded.
                </Typography>
              )}
            </Box>
          );
        })}
      </Box>
    </Panel>
  );
}
