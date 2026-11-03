#!/bin/sh
# Runs on the server, as root (Terraform's deploy step calls it). Swaps in the release Terraform uploaded, builds the
# image there (natively, on arm64) and starts the stack, then waits until the manifest answers over HTTPS.
#
#   /opt/narration/release/        the new release, unzipped by Terraform
#   /opt/narration/narration.env   the settings, from your project's .env
#   /opt/narration/app/            the release that runs
set -eu
ROOT=/opt/narration

if [ ! -s "$ROOT/narration.env" ]; then
  echo "✗ $ROOT/narration.env is missing" >&2
  exit 1
fi
install -m 600 "$ROOT/narration.env" "$ROOT/release/deploy/.env"

rm -rf "$ROOT/previous"
[ -d "$ROOT/app" ] && mv "$ROOT/app" "$ROOT/previous"
mv "$ROOT/release" "$ROOT/app"

cd "$ROOT/app/deploy"
docker compose up -d --build --remove-orphans
# Caddy mounts the Caddyfile by path; an unchanged container keeps reading the old release's file, so restart it when
# the file changed.
if ! cmp -s "$ROOT/previous/deploy/Caddyfile" Caddyfile 2>/dev/null; then
  docker compose restart caddy
fi
docker image prune -f >/dev/null 2>&1 || true

ORIGIN=$(sed -n 's/^PUBLIC_ORIGIN=//p' .env | tr -d "\"'")
HOST=${ORIGIN#https://}
URL="$ORIGIN/.well-known/stellar-agent-services.json"
echo "… waiting for $URL (the first certificate can take a minute)"
for _ in $(seq 1 60); do
  # Through this machine's own port 443, with the public name, so the certificate is checked as clients see it.
  if curl -fsS -o /dev/null --connect-timeout 5 --max-time 20 --resolve "$HOST:443:127.0.0.1" "$URL" 2>/dev/null; then
    echo "✓ live at $ORIGIN"
    exit 0
  fi
  sleep 5
done
echo "✗ $URL is not answering. Logs: sudo docker compose -f $ROOT/app/deploy/docker-compose.yml logs" >&2
docker compose ps >&2
docker compose logs --tail 40 narration >&2 || true
exit 1
