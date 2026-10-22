#!/usr/bin/env bash
# Build this agent for linux/amd64 and linux/arm64, push it to your Artifact Registry repository,
# and print its link by digest, the form Veriphex accepts.
#
#   ./build.sh --repo us-central1-docker.pkg.dev/<project>/agents [--name invoice-checker] [--tag v1]
set -euo pipefail

REPO=""; NAME="my-agent"; TAG="v1"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --tag) TAG="${2:-}"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -n "$REPO" ] || { echo "--repo is required, e.g. us-central1-docker.pkg.dev/my-project/agents" >&2; exit 2; }
REPO="${REPO%/}"
HOST="${REPO%%/*}"

cd "$(dirname "$0")"
if ! grep -q "\"$HOST\"" "${HOME}/.docker/config.json" 2>/dev/null; then
  echo "Docker is not signed in to $HOST. Run: gcloud auth configure-docker $HOST" >&2
  exit 1
fi

META="$(mktemp)"
trap 'rm -f "$META"' EXIT
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag "$REPO/$NAME:$TAG" --push --metadata-file "$META" .
DIGEST="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["containerimage.digest"])' "$META")"
case "$DIGEST" in sha256:*) ;; *) echo "the build reported no digest" >&2; exit 1 ;; esac

echo
echo "Package link:"
echo "$REPO/$NAME@$DIGEST"
