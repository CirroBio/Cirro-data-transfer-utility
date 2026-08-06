import { Alert, Box, Button, Chip, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { api } from "../api";
import type { CredentialsStatus } from "../types";
import { COLOR_MUTED, COLOR_SUCCESS, monoHeadingSx } from "../theme";
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

export default function CredentialsPanel({ status, onChanged, onError }: Props) {
  const [aws, setAws] = useState({
    access_key_id: "",
    secret_access_key: "",
    session_token: "",
    region: "",
  });
  const [busy, setBusy] = useState(false);

  const insecure = window.location.protocol !== "https:" && window.location.hostname !== "localhost";

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

        <Typography variant="body2" sx={{ color: COLOR_MUTED, mt: 2.5 }}>
          With nothing set here, each source falls back to the ambient chain on the server
          (environment, <code>~/.aws</code>, gcloud ADC), then to anonymous access for public
          objects. <code>gs://</code> sources the server has no credentials for should be
          presigned into <code>https://</code> URLs first
          (<code>scripts/gcs_presign.py</code>). <code>ftp://</code> and <code>sftp://</code>{" "}
          carry their own credentials in the plan's <code>source_location</code>.
        </Typography>
      </Box>
    </Panel>
  );
}
