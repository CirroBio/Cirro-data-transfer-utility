FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# config.frontend_dist resolves to <repo root>/frontend/dist relative to backend/.
COPY --from=frontend /build/dist ./frontend/dist

# Everything the app writes lives on the /home/cirro mount: the SQLite DB, the
# staging and scratch tempdirs, and the cached Cirro login token (no keyring in
# a container, so the SDK falls back to a plaintext file here). HOME is set
# explicitly because Docker does not derive it from USER.
ENV HOME=/home/cirro \
    CIRRO_TRANSFER_HOME=/home/cirro \
    CIRRO_HOME=/home/cirro/.cirro \
    PYTHONUNBUFFERED=1

# COPY preserves the host's file modes, which are 0600 on some checkouts — the
# non-root user below could not read its own application code without this.
RUN chmod -R a+rX /app \
    && useradd --create-home --home-dir /home/cirro --uid 1000 cirro
USER cirro
VOLUME /home/cirro

EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
