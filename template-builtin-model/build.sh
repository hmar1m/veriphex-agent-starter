#!/usr/bin/env bash
# Build this agent and its model for linux/amd64 and linux/arm64, push it, and print its link.
#
#   ./build.sh --repo us-central1-docker.pkg.dev/<project>/agents \
#     --model-url https://…/model.gguf --model-sha256 <hex> [--name my-model-agent] [--tag v1]
set -euo pipefail

REPO=""; NAME="my-model-agent"; TAG="v1"; MODEL_URL=""; MODEL_SHA256=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --tag) TAG="${2:-}"; shift 2 ;;
    --model-url) MODEL_URL="${2:-}"; shift 2 ;;
    --model-sha256) MODEL_SHA256="${2:-}"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -n "$REPO" ] && [ -n "$MODEL_URL" ] && [ -n "$MODEL_SHA256" ] \
  || { echo "--repo, --model-url and --model-sha256 are required" >&2; exit 2; }
REPO="${REPO%/}"

cd "$(dirname "$0")"
META="$(mktemp)"
trap 'rm -f "$META"' EXIT
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg MODEL_URL="$MODEL_URL" --build-arg MODEL_SHA256="$MODEL_SHA256" \
  --tag "$REPO/$NAME:$TAG" --push --metadata-file "$META" .
DIGEST="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["containerimage.digest"])' "$META")"
echo
echo "Package link:"
echo "$REPO/$NAME@$DIGEST"
