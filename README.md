# Sanket — AI emergency triage agent

Turns a flood of messy, multilingual emergency reports into a short, ranked list of
de-duplicated incidents, each routed to the right department.

> Work in progress — built phase by phase. Full setup, architecture and demo guide land in Phase 10.

## Run locally

```bash
cp .env.example .env            # then set CALLER_SALT to a long random string
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
(cd backend && .venv/bin/uvicorn app.main:create_app --factory --port 8010)
(cd frontend && npm install && npm run dev)   # http://localhost:5190
```

Post a report:

```bash
curl -X POST localhost:8010/reports -H 'content-type: application/json' \
  -d '{"text":"aag lagi hai sector 18","channel":"sms","caller":"+919999999999"}'
```

Tests: `cd backend && .venv/bin/pytest -q`
