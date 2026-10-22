#!/usr/bin/env bash
# Start the built-in model on the CPU, wait for it, run the agent, stop the model.
set -euo pipefail
/app/llama-server -m /models/model.gguf --host 127.0.0.1 --port 8081 --jinja \
  --ctx-size "${LLAMA_CTX:-8192}" --threads "$(nproc)" >/tmp/llama.log 2>&1 &
LLAMA=$!
trap 'kill "$LLAMA" 2>/dev/null || true' EXIT
for _ in $(seq 1 300); do
  curl -sf http://127.0.0.1:8081/health >/dev/null && break
  sleep 1
done
python3 /agent/agent.py
