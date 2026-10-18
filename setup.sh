#!/usr/bin/env bash
# One-time setup: .env, backend venv + deps, local model, embedding model cache,
# frontend deps, and a clean demo database with the demo account.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

if [ ! -f .env ]; then
  cp .env.example .env
  salt="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i.bak "s|^CALLER_SALT=.*|CALLER_SALT=$salt|" .env && rm -f .env.bak
  echo "Created .env with a random CALLER_SALT (add LLM keys there for live mode)."
fi

echo "==> Backend dependencies"
[ -d backend/.venv ] || "$PY" -m venv backend/.venv
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt

echo "==> Training the local classifier"
(cd backend && .venv/bin/python -m scripts.train_local)

echo "==> Caching the multilingual embedding model (so the demo also works offline)"
(cd backend && .venv/bin/python -c \
  "from app.config import get_settings; from sentence_transformers import SentenceTransformer as S; S(get_settings().embedding_model)") \
  || echo "    could not download it now; the app falls back to hashed n-gram embeddings"

echo "==> Frontend dependencies"
npm --prefix frontend ci --no-audit --no-fund --loglevel=error

echo "==> Clean demo database"
(cd backend && .venv/bin/python -m scripts.seed_demo)
