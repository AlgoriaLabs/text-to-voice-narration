# Text to Speech Narration: the FastAPI app (Kokoro-82M on the CPU) and the Provider Kit gateway in one container.
# The app listens on 127.0.0.1:8000, inside the container only, and the gateway on port 8787, in front of it.
# Builds for arm64 (Oracle Cloud's Ampere A1) and amd64 alike.
#
#   docker build -t text-to-voice-narration .
#   docker run -p 8787:8787 -v narration-data:/data --env-file .env -e PUBLIC_ORIGIN=https://your.domain text-to-voice-narration
#
# Paid jobs are kept in /data/jobs.sqlite and audio files in /data/audio: give /data a persistent volume. Something in
# front must serve /data/audio at <PUBLIC_ORIGIN>/audio/ (deploy/Caddyfile does). The image holds no Stellar secret key.

FROM node:24-trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/*
ENV NODE_ENV=production PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH \
    JOB_DB_PATH=/data/jobs.sqlite DATA_DIR=/data MODELS_DIR=/models
WORKDIR /app

# The model first: it changes least and is the largest layer. Checked against pinned SHA-256 hashes.
ARG KOKORO_MODEL=kokoro-v1.0.onnx
ENV KOKORO_MODEL=$KOKORO_MODEL
COPY scripts/download-models.sh scripts/
RUN sh scripts/download-models.sh /models "$KOKORO_MODEL"

COPY requirements.txt ./
RUN python3 -m venv /opt/venv && pip install --no-cache-dir -r requirements.txt
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY app.py provider.config.json start.sh ./
COPY narration ./narration
# Files can arrive owner-only (mode 600) from the build context; the service runs as the node user, so make
# everything readable.
RUN chmod -R a+rX /app

RUN mkdir -p /data && chown node:node /data
VOLUME /data
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD node -e "Promise.all([8787, 8000].map((p) => fetch('http://127.0.0.1:' + p + '/healthz'))).then((r) => process.exit(r.every((x) => x.ok) ? 0 : 1), () => process.exit(1))"
# A host's new volume may belong to root: started as root, the container gives /data to the node user, then runs the
# service as node. Started as another user, it runs as that user.
ENTRYPOINT ["sh", "-c", "if [ \"$(id -u)\" = 0 ]; then chown -R node:node /data 2>/dev/null || true; exec setpriv --reuid=node --regid=node --init-groups -- \"$@\"; fi; exec \"$@\"", "sh"]
CMD ["sh", "start.sh"]
