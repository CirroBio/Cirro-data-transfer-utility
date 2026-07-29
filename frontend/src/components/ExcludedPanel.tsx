import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@mui/material";
import { useState } from "react";
import { formatBytes } from "../format";
import type { ExcludedDataset } from "../types";
import { COLOR_MUTED, FONT_MONO } from "../theme";
import Panel from "./Panel";

interface Props {
  excluded: ExcludedDataset[];
}

export default function ExcludedPanel({ excluded }: Props) {
  const [open, setOpen] = useState(false);
  if (excluded.length === 0) return null;

  return (
    <Panel
      title="Excluded by plan"
      count={excluded.length}
      actions={
        <Button size="small" variant="outlined" color="secondary" onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show"}
        </Button>
      }
    >
      {open && (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Source dataset</TableCell>
              <TableCell>Study</TableCell>
              <TableCell>Files</TableCell>
              <TableCell>Size</TableCell>
              <TableCell>Excluded at</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {excluded.map((e) => (
              <TableRow key={`${e.study}/${e.source_dataset_id}`}>
                <TableCell sx={{ fontFamily: FONT_MONO, fontSize: 12 }}>
                  {e.source_dataset_id}
                </TableCell>
                <TableCell sx={{ color: COLOR_MUTED }}>{e.study}</TableCell>
                <TableCell>{e.n_files ?? "—"}</TableCell>
                <TableCell>{formatBytes(e.total_size_bytes)}</TableCell>
                <TableCell sx={{ color: COLOR_MUTED }}>{e.excluded_at || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
