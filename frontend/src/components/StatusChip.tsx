import { Chip } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { COLOR_ERROR, COLOR_MUTED, COLOR_SECONDARY, COLOR_SUCCESS, COLOR_WARNING } from "../theme";

/** Statuses the backend will accept for transfer (backend/models.py Status.TRANSFERABLE). */
export const TRANSFERABLE_STATUSES = ["PENDING", "MISMATCH", "FAILED", "CANCELLED"];

const STATUS_COLOR: Record<string, string> = {
  DONE: COLOR_SUCCESS,
  PRESENT: COLOR_SUCCESS,
  FAILED: COLOR_ERROR,
  MISMATCH: COLOR_WARNING,
  CANCELLED: COLOR_WARNING,
  PENDING: COLOR_MUTED,
  VALIDATING: COLOR_SECONDARY,
  DOWNLOADING: COLOR_SECONDARY,
  UPLOADING: COLOR_SECONDARY,
  VERIFYING: COLOR_SECONDARY,
  RUNNING: COLOR_SECONDARY,
  QUEUED: COLOR_MUTED,
};

export default function StatusChip({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? COLOR_MUTED;
  return (
    <Chip
      size="small"
      label={status}
      sx={{
        height: 20,
        fontSize: 11,
        color,
        bgcolor: alpha(color, 0.12),
        border: `1px solid ${alpha(color, 0.35)}`,
      }}
    />
  );
}
