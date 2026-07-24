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
async def upload_csv(dataset_plan: UploadFile, file_plan: UploadFile) -> dict:
    dataset_text = (await dataset_plan.read()).decode("utf-8-sig")
    file_text = (await file_plan.read()).decode("utf-8-sig")
    known = gateway.process_identifiers() if gateway.connected else None
    try:
        specs, excluded = csv_loader.load(dataset_text, file_text, known_processes=known)
    except csv_loader.CsvError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors})
    csv_loader.persist(specs, excluded)
    return {
        "loaded": len(specs),
        "excluded": len(excluded),
        "datasets": [{"key": s.key, "name": s.name, "files": len(s.files)} for s in specs],
    }


# ---- datasets & reconcile ----------------------------------------------

@app.get("/datasets")
def datasets() -> List[dict]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM datasets ORDER BY study, folder_path, name"
        ).fetchall()
        out = []
        for r in rows:
            files = conn.execute(
                "SELECT relative_path, source_uri, expected_size, status, verify_tier, "
                "downloaded_bytes FROM files WHERE dataset_key=? ORDER BY relative_path",
                (r["key"],),
            ).fetchall()
            item = dict(r)
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
            item["files"] = [dict(f) for f in files]
            out.append(item)
    return out


@app.get("/excluded")
def excluded_datasets() -> List[dict]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM excluded_datasets ORDER BY study, source_dataset_id"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/folders")
def folders() -> dict:
    """Level-3 view: the folder tree grouped by study, with a dataset count per
    folder."""
    with db.read() as conn:
        rows = conn.execute(
            "SELECT study, folder_path, COUNT(*) n FROM datasets "
            "GROUP BY study, folder_path ORDER BY study, folder_path"
        ).fetchall()
    tree: dict = {}
    for r in rows:
        tree.setdefault(r["study"], []).append(
            {"folder_path": r["folder_path"], "datasets": r["n"]}
        )
    return tree


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
            keys = [
                r["key"]
                for r in conn.execute(
                    "SELECT key FROM datasets WHERE status IN (?, ?, ?)",
                    (Status.PENDING, Status.MISMATCH, Status.FAILED),
                ).fetchall()
            ]
    else:
        keys = body.get("keys") or []
    queued = transfer_queue.enqueue(keys)
    return {"queued": queued}


@app.post("/retry")
def retry(body: dict = Body(default={})) -> dict:
    _require_connected()
    key = body.get("key")
    if key:
        keys = [key]
    else:
        with db.read() as conn:
            keys = [
                r["key"]
                for r in conn.execute(
                    "SELECT key FROM datasets WHERE status=?", (Status.FAILED,)
                ).fetchall()
            ]
    return {"queued": transfer_queue.enqueue(keys)}


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
