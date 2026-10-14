#!/usr/bin/env bash
# Upload landing/ to emvoox.com on DreamHost over SSH (rsync).
#   scripts/deploy_landing.sh          dry run: lists what would change, uploads nothing
#   scripts/deploy_landing.sh --live   uploads
# Needs an SSH host alias "emvoox" in ~/.ssh/config (see landing/README.md). Override with EMVOOX_DEPLOY_HOST / _DIR.
set -euo pipefail

HOST="${EMVOOX_DEPLOY_HOST:-emvoox}"
DEST="${EMVOOX_DEPLOY_DIR:-emvoox.com}"   # the site's web directory, relative to the SSH user's home
cd "$(dirname "$0")/.."

FLAGS=(-avz --itemize-changes
       --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r   # DreamHost: directories 755, files 644
       --exclude README.md --exclude .DS_Store)

if [[ "${1:-}" == "--live" ]]; then
  echo "Uploading landing/ to $HOST:$DEST/"
else
  FLAGS+=(--dry-run)
  echo "Dry run (nothing is uploaded). Re-run with --live to upload."
fi

rsync "${FLAGS[@]}" landing/ "$HOST:$DEST/"
