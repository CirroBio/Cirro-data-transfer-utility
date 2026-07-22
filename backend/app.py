"""FastAPI application: auth, CSV loading, reconcile, transfer queue, SSE, and
static serving of the built frontend."""
from __future__ import annotations

import asyncio
import json
import queue as _queue
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import csv_loader, db, reconcile
from backend.cirro_gateway import gateway
from backend.config import config
from backend.events import broker
from backend.models import Status
from backend.queue import TransferQueue

app = FastAPI(title="Cirro Data Transfer Utility")
transfer_queue = TransferQueue(gateway=gateway, concurrency=config.concurrency)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    transfer_queue.start()


# ---- auth ---------------------------------------------------------------

@app.post("/auth/login")
def auth_login() -> dict:
    return gateway.start_login()


@app.get("/auth/status")
def auth_status() -> dict:
    return gateway.auth_status()


# ---- browse -------------------------------------------------------------

@app.get("/projects")
def projects() -> List[dict]:
    _require_connected()
    return gateway.list_projects()


@app.get("/processes")
def processes() -> List[dict]:
    _require_connected()
    return gateway.list_ingest_processes()


# ---- CSV ----------------------------------------------------------------

@app.post("/csv")
async def upload_csv(datasets: UploadFile, files: UploadFile) -> dict:
    datasets_text = (await datasets.read()).decode("utf-8-sig")
    files_text = (await files.read()).decode("utf-8-sig")
    known = gateway.process_identifiers() if gateway.connected else None
    try:
        specs = csv_loader.load(datasets_text, files_text, known_processes=known)
    except csv_loader.CsvError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors})
    csv_loader.persist(specs)
    return {
        "loaded": len(specs),
        "datasets": [{"name": s.name, "files": len(s.files)} for s in specs],
    }


# ---- datasets & reconcile ----------------------------------------------

@app.get("/datasets")
def datasets() -> List[dict]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM datasets ORDER BY name").fetchall()
        out = []
        for r in rows:
            files = conn.execute(
                "SELECT relative_path, source_uri, expected_size, status, verify_tier, "
                "downloaded_bytes FROM files WHERE dataset_name=? ORDER BY relative_path",
                (r["name"],),
            ).fetchall()
            item = dict(r)
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
            item["files"] = [dict(f) for f in files]
            out.append(item)
    return out


@app.post("/reconcile")
def do_reconcile(body: dict = Body(default={})) -> List[dict]:
    _require_connected()
    default_project = body.get("default_project") or transfer_queue.default_project
    return reconcile.reconcile_all(gateway, default_project)


# ---- transfer -----------------------------------------------------------

@app.post("/transfer")
def transfer(body: dict = Body(default={})) -> dict:
    _require_connected()
    if body.get("all"):
        with db.read() as conn:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM datasets WHERE status IN (?, ?, ?)",
                    (Status.PENDING, Status.MISMATCH, Status.FAILED),
                ).fetchall()
            ]
    else:
        names = body.get("names") or []
    queued = transfer_queue.enqueue(names)
    return {"queued": queued}


@app.post("/retry")
def retry(body: dict = Body(default={})) -> dict:
    _require_connected()
    name = body.get("name")
    if name:
        names = [name]
    else:
        with db.read() as conn:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM datasets WHERE status=?", (Status.FAILED,)
                ).fetchall()
            ]
    return {"queued": transfer_queue.enqueue(names)}


@app.get("/queue")
def get_queue() -> List[dict]:
    return transfer_queue.snapshot()


@app.post("/config")
def set_config(body: dict = Body(default={})) -> dict:
    if "default_project" in body:
        transfer_queue.default_project = body["default_project"] or None
    return {
        "default_project": transfer_queue.default_project,
        "concurrency": transfer_queue.concurrency,
        "base_url": config.base_url,
    }


# ---- SSE ----------------------------------------------------------------

@app.get("/events")
async def events() -> StreamingResponse:
    q = broker.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = await asyncio.to_thread(q.get, True, 15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except _queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            broker.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---- helpers & static ---------------------------------------------------

def _require_connected() -> None:
    if not gateway.connected:
        raise HTTPException(status_code=409, detail="Not connected to Cirro. Log in first.")


# Serve the built frontend if present (mounted last so it doesn't shadow the API).
if config.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(config.frontend_dist), html=True), name="frontend")
else:
    @app.get("/")
    def placeholder() -> dict:
        return {
            "app": "Cirro Data Transfer Utility",
            "frontend": "not built — run `npm install && npm run build` in frontend/",
            "docs": "/docs",
        }
