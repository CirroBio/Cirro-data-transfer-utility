import { useState } from "react";
import type { AuthStatus } from "../types";

interface Props {
  auth: AuthStatus;
  onLogin: () => void;
}

// Renders the auth_message markdown links (Cirro returns "[url](url) enter CODE").
function renderMessage(markdown: string) {
  return markdown.split(/\s+/).map((part, i) => {
    const link = part.match(/^\[(.+)\]\((.+)\)$/);
    if (link) {
      return (
        <a key={i} href={link[2]} target="_blank" rel="noreferrer">
          {link[1]}{" "}
        </a>
      );
    }
    return <span key={i}>{part} </span>;
  });
}

export default function AuthPanel({ auth, onLogin }: Props) {
  const [starting, setStarting] = useState(false);
  const pending = auth.status === "pending" || (starting && auth.status !== "connected");

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Cirro Connection</h2>
      </div>
      <div className="conn">
        <span className={`status-pill`}>
          <span className={`dot ${auth.status}`} />
          {auth.status}
        </span>
        {auth.user && <span className="muted">as {auth.user}</span>}
        <span className="faint">· {auth.base_url}</span>
        <div className="spacer" />
        {auth.status !== "connected" && (
          <button
            onClick={() => {
              setStarting(true);
              onLogin();
            }}
            disabled={pending}
          >
            {pending ? "Waiting for browser…" : "Log in"}
          </button>
        )}
      </div>
      {auth.status === "pending" && auth.auth_message && (
        <p className="auth-code">{renderMessage(auth.auth_message)}</p>
      )}
      {auth.error && <p className="error" style={{ marginBottom: 0 }}>{auth.error}</p>}
    </div>
  );
}
