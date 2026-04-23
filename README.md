# H2L Thesis Local Demo

This repository runs the thesis dashboard as a single local FastAPI app. The same server serves the React UI, runtime status endpoints, live H2L/RAG analysis, audit workflow, and thesis artifact checks.

## Run The Full Web App

Build the frontend once, then start the single server from the repository root:

```bash
cd frontend
npm run build
cd ..
python api.py
```

Open:

```text
http://127.0.0.1:8000/
```

For cloud/runtime deployment, install from `requirements.txt` and start with:

```bash
uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
```

Do not run Vite for the full demo. `npm run dev` is only for frontend-only development.

## Readiness Endpoints

- `GET /health` checks the API and detector basics.
- `GET /runtime/status` shows model/index/runtime warmup state.
- `GET /thesis/status` verifies thesis-facing readiness: one-server UI build, taxonomy, runtime components, proper RAG pairs, sentence polarity artifacts, statistical artifacts, sensitivity artifacts, vector index, and no-mock response contract.
- `GET /evaluation-summary` returns artifact-backed research metrics.
- `GET /evaluation-progress` returns live evaluator progress from real progress artifacts on disk while proper evaluation or sentence polarity runs are in progress.

## Runtime Contract

- Current-case results come from `H2LDetectorV3` plus live retrieval runtime.
- Current-case metrics are operational observations only, such as candidate count, accepted/filter ratios, severity, and retrieved evidence count.
- Thesis research metrics such as MAP, MRR, nDCG, statistical tests, and sensitivity values come only from evaluation artifacts.
- The app does not silently fall back to mock/sample results when runtime analysis fails.
- Stable aliases such as `proper_eval_latest_*`, `proper_eval_checkpoint_*`, and `sentence_polarity_latest.json` are the primary sources for the dashboard; timestamped history is retained only in a small rolling window to avoid artifact sprawl.

## Checks

```bash
cd frontend
npm run lint
npm run build
npm run smoke:cdp
```

`npm run smoke:cdp` expects the FastAPI app to be running at `http://127.0.0.1:8000/` and Chrome DevTools Protocol available on `127.0.0.1:9222`.
