import { Alert, Box, Button, Chip, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { CredentialsStatus } from "../types";
import { COLOR_BORDER, COLOR_MUTED, COLOR_SUCCESS, monoHeadingSx } from "../theme";
import Panel from "./Panel";

interface Props {
  status: CredentialsStatus | null;
  onChanged: (status: CredentialsStatus) => void;
  onError: (msg: string) => void;
}

const SECRET_FIELD_PROPS = {
  type: "password",
  autoComplete: "off",
  spellCheck: false,
} as const;

function ProviderHeading({ label, configured, hint }: {
  label: string;
  configured: boolean;
  hint: string | null;
}) {
  return (
    <Stack direction="row" alignItems="center" spacing={1}>
      <Typography sx={monoHeadingSx}>{label}</Typography>
      <Chip
        size="small"
        label={configured ? "set" : "not set"}
        sx={{
          height: 20,
          fontSize: 11,
          ...(configured ? { color: COLOR_SUCCESS, borderColor: COLOR_SUCCESS } : {}),
        }}
        variant="outlined"
      />
      {hint && (
        <Typography variant="body2" sx={{ color: COLOR_MUTED }}>
          {hint}
        </Typography>
      )}
    </Stack>
  );
}

/** Age of the pasted GCP token, flagged once it is past its nominal lifetime. */
function gcpTokenAge(status: CredentialsStatus | null): string | null {
  const age = status?.gcp.age_seconds;
  if (age === null || age === undefined) return null;
  const minutes = Math.floor(age / 60);
  const label = minutes < 1 ? "just now" : `${minutes} min ago`;
  return age >= status!.gcp.nominal_lifetime_seconds
    ? `pasted ${label} — likely expired`
    : `pasted ${label}`;
}

export default function CredentialsPanel({ status, onChanged, onError }: Props) {
  const [aws, setAws] = useState({
    access_key_id: "",
    secret_access_key: "",
    session_token: "",
    region: "",
  });
  const [gcpToken, setGcpToken] = useState("");
  const [busy, setBusy] = useState(false);

  const insecure = window.location.protocol !== "https:" && window.location.hostname !== "localhost";

  // The GCP token's reported age is server-side, so refresh it while this panel
  // is open — otherwise "likely expired" would never appear without a reload.
  useEffect(() => {
    const id = window.setInterval(() => {
      api.credentials().then(onChanged).catch(() => {});
    }, 30_000);
    return () => window.clearInterval(id);
  }, [onChanged]);

  async function submit(fn: () => Promise<CredentialsStatus>, clear: () => void) {
    setBusy(true);
    try {
      onChanged(await fn());
      clear(); // Drop the plaintext from component state once accepted.
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Source Credentials"
      subtitle="Held in memory for this session only — never written to disk"
    >
      <Box sx={{ px: 3, py: 2.5 }}>
        {insecure && (
          <Alert severity="warning" sx={{ mb: 2.5 }}>
            This page is served over plain HTTP from a non-local host, so anything you submit
            here travels unencrypted. Put TLS in front of the app before entering real keys.
          </Alert>
        )}

        <ProviderHeading
          label="AWS"
          configured={status?.aws.configured ?? false}
          hint={
            status?.aws.configured
              ? [status.aws.hint, status.aws.temporary ? "temporary (STS)" : "long-lived",
                 status.aws.region].filter(Boolean).join(" · ")
              : null
          }
        />
        <Stack direction="row" spacing={2} sx={{ mt: 1.5, mb: 1.5 }}>
          <TextField
            label="Access key id"
            size="small"
            autoComplete="off"
            spellCheck={false}
            value={aws.access_key_id}
            onChange={(e) => setAws({ ...aws, access_key_id: e.target.value })}
          />
          <TextField
            label="Secret access key"
            size="small"
            {...SECRET_FIELD_PROPS}
            value={aws.secret_access_key}
            onChange={(e) => setAws({ ...aws, secret_access_key: e.target.value })}
          />
          <TextField
            label="Session token (STS only)"
            size="small"
            {...SECRET_FIELD_PROPS}
            value={aws.session_token}
            onChange={(e) => setAws({ ...aws, session_token: e.target.value })}
          />
          <TextField
            label="Region"
            size="small"
            sx={{ maxWidth: 140 }}
            autoComplete="off"
            value={aws.region}
            onChange={(e) => setAws({ ...aws, region: e.target.value })}
          />
        </Stack>
        <Stack direction="row" spacing={1.5}>
          <Button
            variant="contained"
            color="secondary"
            disabled={busy || !aws.access_key_id || !aws.secret_access_key}
            onClick={() =>
              submit(
                () =>
                  api.setAwsCredentials({
                    access_key_id: aws.access_key_id,
                    secret_access_key: aws.secret_access_key,
                    session_token: aws.session_token || undefined,
                    region: aws.region || undefined,
                  }),
                () =>
                  setAws({
                    access_key_id: "",
                    secret_access_key: "",
                    session_token: "",
                    region: "",
                  }),
              )
            }
          >
            Save AWS credentials
          </Button>
          {status?.aws.configured && (
            <Button
              variant="outlined"
              color="error"
              disabled={busy}
              onClick={() => submit(() => api.clearCredentials("aws"), () => {})}
            >
              Clear
            </Button>
          )}
        </Stack>

        <Box sx={{ borderTop: `1px solid ${COLOR_BORDER}`, my: 2.5 }} />

        <ProviderHeading
          label="Google Cloud"
          configured={status?.gcp.configured ?? false}
          hint={gcpTokenAge(status)}
        />
        <Typography variant="body2" sx={{ color: COLOR_MUTED, mt: 1 }}>
          Generate a token with <code>gcloud auth print-access-token</code> and paste it
          below. It is a bearer token that cannot be refreshed, so it stops working after
          about an hour — paste a fresh one when a transfer starts failing on{" "}
          <code>gs://</code> sources.
        </Typography>
        <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 1.5, mb: 1.5 }}>
          <TextField
            label="Access token"
            size="small"
            sx={{ flex: 1, maxWidth: 520 }}
            {...SECRET_FIELD_PROPS}
            value={gcpToken}
            onChange={(e) => setGcpToken(e.target.value)}
          />
        </Stack>
        <Stack direction="row" spacing={1.5}>
          <Button
            variant="contained"
            color="secondary"
            disabled={busy || !gcpToken.trim()}
            onClick={() =>
              submit(() => api.setGcpCredentials(gcpToken), () => setGcpToken(""))
            }
          >
            Save access token
          </Button>
          {status?.gcp.configured && (
            <Button
              variant="outlined"
              color="error"
              disabled={busy}
              onClick={() => submit(() => api.clearCredentials("gcp"), () => {})}
            >
              Clear
            </Button>
          )}
        </Stack>

        <Typography variant="body2" sx={{ color: COLOR_MUTED, mt: 2.5 }}>
          With nothing set here, each source falls back to the ambient chain on the server
          (environment, <code>~/.aws</code>, gcloud ADC), then to anonymous access for public
          objects. <code>ftp://</code> and <code>sftp://</code> carry their own credentials in
          the plan's <code>source_location</code>.
        </Typography>
      </Box>
    </Panel>
  );
}
