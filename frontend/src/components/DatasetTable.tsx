import {
  Box,
  Button,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { Fragment, useState } from "react";
import { api } from "../api";
import { formatBytes } from "../format";
import type { Dataset } from "../types";
import { COLOR_BORDER, COLOR_ERROR, COLOR_GRAY, COLOR_MUTED, FONT_MONO } from "../theme";
import Panel from "./Panel";
import StatusChip, { TRANSFERABLE_STATUSES } from "./StatusChip";

interface Props {
  datasets: Dataset[];
  connected: boolean;
  onChanged: () => void;
}

// cirro_folder_path is rooted at the study (= project); the in-project folder
// is that path with the study prefix removed.
function folderInProject(study: string, folderPath: string): string {
  if (folderPath === study) return "";
  return folderPath.startsWith(study + "/") ? folderPath.slice(study.length + 1) : folderPath;
}

const mono = { fontFamily: FONT_MONO, fontSize: 12 };

export default function DatasetTable({ datasets, connected, onChanged }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (datasets.length === 0) {
    return (
      <Panel title="Datasets" count={0}>
        <Box sx={{ px: 3, py: 5, textAlign: "center" }}>
          <Typography variant="body2">
            No datasets loaded. Choose your <strong>dataset_plan.csv</strong> and{" "}
            <strong>file_plan.csv</strong> above, then <strong>Load plan</strong>.
          </Typography>
        </Box>
      </Panel>
    );
  }

  return (
    <Panel title="Datasets" count={datasets.length}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Project (study)</TableCell>
            <TableCell>Folder</TableCell>
            <TableCell>Data type</TableCell>
            <TableCell>Files</TableCell>
            <TableCell>Status</TableCell>
            <TableCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {datasets.map((d) => {
            const folder = folderInProject(d.study, d.folder_path);
            return (
              <Fragment key={d.key}>
                <TableRow>
                  <TableCell>
                    <Typography variant="body1" sx={{ fontWeight: 600 }}>
                      {d.name}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ color: COLOR_MUTED }}>{d.study || "—"}</TableCell>
                  <TableCell sx={{ ...mono, color: COLOR_MUTED }}>{folder || "/"}</TableCell>
                  <TableCell sx={{ color: COLOR_MUTED }} title={d.data_type}>
                    {d.cirro_type_name || d.data_type}
                  </TableCell>
                  <TableCell>
                    {d.files.length}
                    {d.planned_files != null && d.planned_files !== d.files.length && (
                      <Box component="span" sx={{ color: COLOR_MUTED }}>
                        {" "}
                        / {d.planned_files}
                      </Box>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusChip status={d.status} />
                    {/* The file in flight is shown in the Transfer Queue panel, not here. */}
                    {d.error && (
                      <Typography sx={{ fontSize: 12, color: COLOR_ERROR, mt: 0.5 }}>
                        {d.error}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button
                        size="small"
                        variant="outlined"
                        color="secondary"
                        onClick={() => setExpanded(expanded === d.key ? null : d.key)}
                      >
                        {expanded === d.key ? "Hide" : "Files"}
                      </Button>
                      {connected && TRANSFERABLE_STATUSES.includes(d.status) && (
                        <Button
                          size="small"
                          variant="contained"
                          color="secondary"
                          onClick={() => api.transfer([d.key]).then(onChanged)}
                        >
                          Transfer
                        </Button>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
                {expanded === d.key && (
                  <TableRow>
                    <TableCell colSpan={7} sx={{ bgcolor: COLOR_GRAY, p: 2 }}>
                      <TableContainer
                        sx={{
                          maxHeight: 320,
                          bgcolor: "#fff",
                          border: `1px solid ${COLOR_BORDER}`,
                          borderRadius: "10px",
                        }}
                      >
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell>Relative path</TableCell>
                            <TableCell>Source</TableCell>
                            <TableCell>Size</TableCell>
                            <TableCell>State</TableCell>
                            <TableCell>Verified by</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {d.files.map((f) => (
                            <TableRow key={f.relative_path}>
                              <TableCell sx={{ ...mono, whiteSpace: "nowrap" }}>
                                {f.relative_path}
                              </TableCell>
                              <TableCell sx={{ ...mono, color: COLOR_MUTED, wordBreak: "break-all" }}>
                                {f.source_uri}
                              </TableCell>
                              <TableCell sx={{ whiteSpace: "nowrap" }}>
                                {formatBytes(f.expected_size)}
                              </TableCell>
                              <TableCell sx={{ whiteSpace: "nowrap" }}>{f.status}</TableCell>
                              <TableCell>
                                {f.verify_tier ? (
                                  <Chip
                                    size="small"
                                    label={f.verify_tier}
                                    sx={{ height: 20, fontSize: 11 }}
                                  />
                                ) : (
                                  "—"
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                      </TableContainer>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </Panel>
  );
}
