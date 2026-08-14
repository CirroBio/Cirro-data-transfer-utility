import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SettingsIcon from "@mui/icons-material/Settings";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Container,
  IconButton,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeEvents } from "./api";
import AuthPanel from "./components/AuthPanel";
import ControlBar from "./components/ControlBar";
import CredentialsPanel from "./components/CredentialsPanel";
import DatasetTable from "./components/DatasetTable";
import ExcludedPanel from "./components/ExcludedPanel";
import QueuePanel from "./components/QueuePanel";
import { AUTH_STATUS_COLOR, COLOR_LOGO_LIGHT, COLOR_MUTED, FONT_MONO } from "./theme";
import type {
  AuthStatus,
  CredentialsStatus,
  Dataset,
  DatasetProgress,
  ExcludedDataset,
  Project,
  QueueItem,
} from "./types";

export default function App() {
  const [auth, setAuth] = useState<AuthStatus>({
    status: "disconnected",
    user: null,
    auth_message: null,
    base_url: "",
    error: null,
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [excluded, setExcluded] = useState<ExcludedDataset[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [defaultProject, setDefaultProject] = useState("");
  const [progress, setProgress] = useState<Record<string, DatasetProgress>>({});
  const [checksumMethod, setChecksumMethod] = useState<string | null>(null);
  const [creds, setCreds] = useState<CredentialsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const connected = auth.status === "connected";
  const refreshTimer = useRef<number | null>(null);

  const reportError = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : String(e));
  }, []);

  const refreshData = useCallback(() => {
    api.datasets().then(setDatasets).catch(reportError);
    api.excluded().then(setExcluded).catch(reportError);
    api.queue().then(setQueue).catch(reportError);
  }, [reportError]);

  // Debounce bursts of SSE-triggered refreshes.
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(refreshData, 300);
  }, [refreshData]);

  // Poll auth status until connected (covers the device-code wait).
  useEffect(() => {
    let active = true;
    const tick = () =>
      api.authStatus().then((s) => {
        if (active) setAuth(s);
      });
    tick();
    const id = window.setInterval(() => {
      if (auth.status !== "connected") tick();
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [auth.status]);

  // Load persisted datasets/queue on mount (they survive restarts and don't
  // require a Cirro connection to display). Credential *presence* is read the
  // same way — the secrets themselves have no read path.
  useEffect(() => {
    refreshData();
    api.credentials().then(setCreds).catch(reportError);
  }, [refreshData, reportError]);

  // On connect, load projects (which do require auth).
  useEffect(() => {
    if (connected) {
      api.projects().then(setProjects).catch(reportError);
      refreshData();
    }
  }, [connected, refreshData, reportError]);

  // Subscribe to the server events once.
  useEffect(() => {
    return subscribeEvents(
      (e) => {
        if (e.type === "progress") {
          // Keep the phases separate: each drives its own bar, and download's
          // `total` is in bytes where the others count files.
          setProgress((p) => ({
            ...p,
            [e.key]: {
              ...p[e.key],
              ...(e.phase === "download"
                ? {
                    download: {
                      ...p[e.key]?.download,
                      file: e.file,
                      bytes: e.bytes,
                      totalBytes: e.total,
                    },
                  }
                : {
                    [e.phase]: {
                      done: e.done,
                      total: e.total,
                      file: e.file,
                      resume: e.resume,
                    },
                  }),
            },
          }));
        }
        // A file finished: advance that phase's file count without refetching.
        if (e.type === "file") {
          setProgress((p) => ({
            ...p,
            [e.key]: {
              ...p[e.key],
              [e.phase]: { ...p[e.key]?.[e.phase], done: e.done, total: e.total },
            },
          }));
        }
        if (e.type === "dataset") {
          if (e.checksum_method) setChecksumMethod(e.checksum_method);
          if (["DONE", "FAILED", "PRESENT"].includes(e.status)) {
            setProgress((p) => {
              const { [e.key]: _drop, ...rest } = p;
              return rest;
            });
          }
          scheduleRefresh();
        }
        if (e.type === "queue") scheduleRefresh();
        if (e.type === "warning") setError(`${e.name}: ${e.message}`);
      },
      // Events were missed: the bars would be stuck mid-transfer, and the
      // tables are only as fresh as the last event that landed.
      () => {
        setProgress({});
        scheduleRefresh();
      },
    );
  }, [scheduleRefresh]);

  return (
    <>
      <AppBar position="sticky">
        <Toolbar variant="dense" sx={{ minHeight: 56 }}>
          <Stack direction="row" alignItems="baseline" spacing={1.5}>
            <Typography
              sx={{
                fontFamily: FONT_MONO,
                fontSize: 15,
                letterSpacing: "0.04em",
                color: COLOR_LOGO_LIGHT,
              }}
            >
              cirro
            </Typography>
            <Typography sx={{ fontSize: 14, color: "#fff" }}>Data Transfer Utility</Typography>
          </Stack>
          <Box sx={{ flex: 1 }} />
          <Typography
            sx={{
              fontSize: 12,
              color: "rgba(255,255,255,0.7)",
              display: { xs: "none", md: "block" },
            }}
          >
            bulk-load external files into Cirro as datasets
          </Typography>
          {/* Connection state stays visible from every page — settings is where
              you change it, not where you have to go to see it. */}
          <Stack direction="row" alignItems="center" spacing={0.75} sx={{ ml: 3, mr: 1 }}>
            <Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                bgcolor: AUTH_STATUS_COLOR[auth.status] ?? COLOR_MUTED,
              }}
            />
            <Typography sx={{ fontSize: 12, color: "rgba(255,255,255,0.85)" }}>
              {connected ? auth.user ?? "connected" : auth.status}
            </Typography>
          </Stack>
          <Tooltip title={showSettings ? "Back to transfers" : "Settings"}>
            <IconButton
              aria-label={showSettings ? "Back to transfers" : "Settings"}
              aria-pressed={showSettings}
              sx={{ color: "#fff" }}
              onClick={() => setShowSettings((v) => !v)}
            >
              {showSettings ? <ArrowBackIcon /> : <SettingsIcon />}
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        {error && (
          <Alert
            severity="error"
            sx={{ mb: 2.5 }}
            action={
              <Button color="inherit" size="small" onClick={() => setError(null)}>
                Dismiss
              </Button>
            }
          >
            {error}
          </Alert>
        )}

        {showSettings ? (
          <>
            <AuthPanel
              auth={auth}
              onLogin={() => api.login().then(setAuth).catch(reportError)}
              onAuth={setAuth}
              onError={setError}
            />
            <CredentialsPanel status={creds} onChanged={setCreds} onError={setError} />
            <Button
              startIcon={<ArrowBackIcon />}
              color="secondary"
              onClick={() => setShowSettings(false)}
            >
              Back to transfers
            </Button>
          </>
        ) : (
          <>
            <ControlBar
              connected={connected}
              projects={projects}
              defaultProject={defaultProject}
              datasetCount={datasets.length}
              onDefaultProject={setDefaultProject}
              onChanged={refreshData}
              onError={setError}
            />
            <DatasetTable datasets={datasets} connected={connected} onChanged={refreshData} />
            <ExcludedPanel excluded={excluded} />
            <QueuePanel
              queue={queue}
              datasets={datasets}
              progress={progress}
              checksumMethod={checksumMethod}
              onChanged={refreshData}
              onError={setError}
            />
          </>
        )}
      </Container>
    </>
  );
}
