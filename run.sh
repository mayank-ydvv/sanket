#!/usr/bin/env bash
# Start the API (:8010) and the web app (:5190). Ctrl-C stops both.
#   ./run.sh          live mode: real LLM providers from .env
#   ./run.sh --demo   offline replay of the recorded disaster run (DEMO_CACHE=true)
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--demo" ]; then
  export DEMO_CACHE=true
  export HF_HUB_OFFLINE=1  # use the embedding model setup.sh cached; never touch the network
  echo "Demo replay: LLM answers come from backend/data/demo_run.jsonl, no provider calls."
fi

backend/.venv/bin/uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8010 &
api=$!
npm --prefix frontend run dev -- --port 5190 --strictPort &
web=$!
trap 'kill $api $web 2>/dev/null; wait' INT TERM EXIT

echo "Open http://localhost:5190 (sign in with the demo account from scripts/seed_demo.py)"
while kill -0 "$api" 2>/dev/null && kill -0 "$web" 2>/dev/null; do sleep 1; done  # bash 3.2 has no wait -n
