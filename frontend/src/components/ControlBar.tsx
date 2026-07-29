import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useRef, useState } from "react";
import { api } from "../api";
import type { Project } from "../types";
import { COLOR_BORDER, COLOR_MUTED, monoHeadingSx } from "../theme";
import Panel from "./Panel";

/** Left-hand label column, shared by this panel's rows and its hint indent. */
const LABEL_WIDTH = 120;

interface Props {
  connected: boolean;
  projects: Project[];
  defaultProject: string;
  datasetCount: number;
  onDefaultProject: (id: string) => void;
  onChanged: () => void;
  onError: (msg: string) => void;
}

export default function ControlBar({
  connected,
  projects,
  defaultProject,
  datasetCount,
  onDefaultProject,
  onChanged,
  onError,
}: Props) {
  const datasetPlanRef = useRef<HTMLInputElement>(null);
  const filePlanRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [chosen, setChosen] = useState<{ datasetPlan?: string; filePlan?: string }>({});

  async function runAction(fn: () => Promise<unknown>) {
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
    const datasetPlan = datasetPlanRef.current?.files?.[0];
    const filePlan = filePlanRef.current?.files?.[0];
    if (!datasetPlan || !filePlan) {
      onError("Choose both dataset_plan.csv and file_plan.csv.");
      return;
    }
    await runAction(() => api.uploadCsv(datasetPlan, filePlan));
  }

  return (
    <Panel
      title="Controls"
      subtitle={!connected ? "Log in to reconcile & transfer" : undefined}
    >
      <Box sx={{ px: 3, py: 2.5 }}>
        {/* Hint below the row rather than as helperText, which would make the
            select taller than its centred siblings and misalign them. */}
        <Stack direction="row" alignItems="center" spacing={2}>
          <Typography variant="body2" sx={{ width: LABEL_WIDTH, flexShrink: 0 }}>
            Fallback project
          </Typography>
          <TextField
            select
            size="small"
            sx={{ minWidth: 260 }}
            value={defaultProject}
            disabled={!connected}
            SelectProps={{ displayEmpty: true }}
            onChange={(e) => {
              onDefaultProject(e.target.value);
              api.setDefaultProject(e.target.value).catch((err) => onError(String(err)));
            }}
          >
            <MenuItem value="">— none —</MenuItem>
            {projects.map((p) => (
              <MenuItem key={p.id} value={p.name}>
                {p.name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Typography
          variant="body2"
          sx={{ color: COLOR_MUTED, mt: 0.75, mb: 2.5, ml: `calc(${LABEL_WIDTH}px + 16px)` }}
        >
          Used only if a dataset row has no study; normally the study is the project.
        </Typography>

        <Stack
          direction="row"
          alignItems="center"
          spacing={2}
          sx={{ mb: 2.5, pb: 2.5, borderBottom: `1px solid ${COLOR_BORDER}` }}
        >
          <Button component="label" variant="outlined" color="secondary">
            {chosen.datasetPlan ?? "dataset_plan.csv"}
            <input
              ref={datasetPlanRef}
              type="file"
              accept=".csv"
              hidden
              onChange={(e) =>
                setChosen((c) => ({ ...c, datasetPlan: e.target.files?.[0]?.name }))
              }
            />
          </Button>
          <Button component="label" variant="outlined" color="secondary">
            {chosen.filePlan ?? "file_plan.csv"}
            <input
              ref={filePlanRef}
              type="file"
              accept=".csv"
              hidden
              onChange={(e) => setChosen((c) => ({ ...c, filePlan: e.target.files?.[0]?.name }))}
            />
          </Button>
          <Button variant="contained" color="secondary" onClick={loadCsv} disabled={busy}>
            Load plan
          </Button>
        </Stack>

        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Button
            variant="contained"
            color="secondary"
            disabled={!connected || busy}
            onClick={() => runAction(() => api.reconcile(defaultProject || null))}
          >
            Reconcile
          </Button>
          <Button
            variant="contained"
            color="secondary"
            disabled={!connected || busy}
            onClick={() => runAction(() => api.transferAll())}
          >
            Transfer all pending
          </Button>
          <Button
            variant="outlined"
            color="secondary"
            disabled={!connected || busy}
            onClick={() => runAction(() => api.retryFailed())}
          >
            Retry failed
          </Button>
          <Box sx={{ flex: 1 }} />
          <Button
            variant="outlined"
            color="error"
            disabled={busy || datasetCount === 0}
            title="Forget the loaded plan. Nothing in Cirro is deleted."
            onClick={() => setConfirmClear(true)}
          >
            Clear plan
          </Button>
        </Stack>
      </Box>

      <Dialog open={confirmClear} onClose={() => setConfirmClear(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={monoHeadingSx}>CLEAR THE LOADED PLAN?</DialogTitle>
        <DialogContent>
          <Typography variant="body1" sx={{ mb: 1.5 }}>
            Removes {datasetCount} dataset{datasetCount === 1 ? "" : "s"}, their file rows, the
            transfer queue and the reconcile cache from this app.
          </Typography>
          <Typography variant="body2" sx={{ color: COLOR_MUTED }}>
            Datasets already transferred <strong>stay in Cirro</strong> — this only clears local
            state. Reload the CSVs to start over.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button color="secondary" onClick={() => setConfirmClear(false)}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            disabled={busy}
            onClick={() => {
              setConfirmClear(false);
              runAction(() => api.clearPlan());
            }}
          >
            Clear plan
          </Button>
        </DialogActions>
      </Dialog>
    </Panel>
  );
}
