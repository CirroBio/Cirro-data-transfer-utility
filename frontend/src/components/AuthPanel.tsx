import { Alert, Box, Button, Chip, Link, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuthStatus } from "../types";
import { AUTH_STATUS_COLOR, COLOR_MUTED, FONT_MONO } from "../theme";
import Panel from "./Panel";

interface Props {
  auth: AuthStatus;
  onLogin: () => Promise<unknown>;
  onAuth: (auth: AuthStatus) => void;
  onError: (msg: string) => void;
}

/** Left-hand label column, shared by this panel's rows and its hint indent. */
const LABEL_WIDTH = 120;

// Cirro returns the device-code prompt as "[url](url) enter CODE". Only http(s)
// links are rendered as anchors — React warns on javascript: URLs but does not
// block them.
function renderMessage(markdown: string) {
  return markdown.split(/\s+/).map((part, i) => {
    const link = part.match(/^\[(.+)\]\((.+)\)$/);
    if (link && /^https?:\/\//i.test(link[2])) {
      return (
        <Link key={i} href={link[2]} target="_blank" rel="noreferrer">
          {link[1]}{" "}
        </Link>
      );
    }
    return <span key={i}>{part} </span>;
  });
}

export default function AuthPanel({ auth, onLogin, onAuth, onError }: Props) {
  const [starting, setStarting] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const pending = auth.status === "pending" || (starting && auth.status !== "connected");
  const connected = auth.status === "connected";

  const report = (e: unknown) => onError(e instanceof Error ? e.message : String(e));

  // Without this, a login that fails leaves the button disabled until reload.
  useEffect(() => {
    if (auth.status === "connected" || auth.status === "error") setStarting(false);
  }, [auth.status]);

  return (
    <Panel title="Cirro Connection">
      <Box sx={{ px: 3, py: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Chip
            size="small"
            label={auth.status}
            icon={
              <Box
                component="span"
                sx={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  bgcolor: AUTH_STATUS_COLOR[auth.status] ?? COLOR_MUTED,
                  ml: 1,
                }}
              />
            }
          />
          {auth.user && <Typography variant="body2">as {auth.user}</Typography>}
          <Typography variant="body2" sx={{ color: COLOR_MUTED }}>
            · {auth.base_url}
          </Typography>
          <Box sx={{ flex: 1 }} />
          {connected ? (
            <Button
              variant="outlined"
              color="secondary"
              onClick={() => api.logout().then(onAuth).catch(report)}
            >
              Log out
            </Button>
          ) : (
            <Button
              variant="contained"
              color="secondary"
              disabled={pending}
              onClick={() => {
                setStarting(true);
                onLogin().finally(() => setStarting(false));
              }}
            >
              {pending ? "Waiting for browser…" : "Log in"}
            </Button>
          )}
        </Stack>

        {/* The hint sits below the row, not as TextField helperText — helper text
            makes that child taller and pushes the centred label and button out of
            line with the input. */}
        <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 2 }}>
          <Typography variant="body2" sx={{ width: LABEL_WIDTH, flexShrink: 0 }}>
            Cirro tenant
          </Typography>
          <TextField
            size="small"
            sx={{ minWidth: 260 }}
            placeholder={auth.base_url || "app.cirro.bio"}
            value={baseUrl}
            disabled={connected}
            autoComplete="off"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <Button
            variant="outlined"
            color="secondary"
            disabled={connected || !baseUrl.trim()}
            onClick={() =>
              api
                .setBaseUrl(baseUrl)
                .then((s) => {
                  onAuth(s);
                  setBaseUrl("");
                })
                .catch(report)
            }
          >
            Use tenant
          </Button>
        </Stack>
        <Typography
          variant="body2"
          sx={{ color: COLOR_MUTED, mt: 0.75, ml: `calc(${LABEL_WIDTH}px + 16px)` }}
        >
          {connected ? "Log out to point at a different tenant" : "Host only, no scheme"}
        </Typography>
        {auth.status === "pending" && auth.auth_message && (
          <Typography sx={{ mt: 2, fontFamily: FONT_MONO, fontSize: 12 }}>
            {renderMessage(auth.auth_message)}
          </Typography>
        )}
        {auth.error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {auth.error}
          </Alert>
        )}
      </Box>
    </Panel>
  );
}
