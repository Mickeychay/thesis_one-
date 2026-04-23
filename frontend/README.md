# H2L Web UI

The production-local setup uses one FastAPI server for both the React UI and the API.

## Run Locally

Build the frontend, then start the single FastAPI server from the repo root:

```bash
cd frontend
npm run build
cd ..
python api.py
```

Open `http://127.0.0.1:8000/`. The same server serves the UI and these API endpoints:

- `GET /health`
- `GET /runtime/status`
- `GET /thesis/status`
- `POST /analyze`
- `GET /evaluation-summary`

## Development Mode

Vite dev mode is optional for frontend-only iteration:

```bash
cd frontend
npm run dev
```

In dev mode, Vite proxies `/api/*` to `http://localhost:8000`.

## Checks

```bash
npm run lint
npm run build
npm run smoke:cdp
```

## Thesis Data Contract

- The current case analysis uses live backend detector/retrieval output.
- Case-level metrics are operational only, not per-case MAP/MRR/nDCG.
- MAP/MRR/nDCG, statistical tests, and sensitivity values are loaded from thesis artifacts and are shown in the Research Report tab with their source functions.
