# H2L Thesis Local Demo

This repository runs the thesis dashboard as a single local FastAPI app. The same server serves the React UI, runtime status endpoints, live H2L/RAG analysis, audit workflow, and thesis artifact checks.

## Run The Full Web App

The simplest way to run the system is using the unified launcher script:

```bash
python start.py
```

This will automatically:
1. Clean up stale processes on ports 8000/5173.
2. Initialize the Backend (FastAPI) and serve the UI on `http://127.0.0.1:8000/`.
3. Restrict access to Localhost only (default security mode for confidential case data).

### Security & Access Modes

- **Localhost Only (Default & Recommended):**
  ```bash
  python start.py
  ```
  Runs securely on `127.0.0.1`. CORS is strictly restricted to local origins.

- **Public Network Mode (Demo/Staging):**
  ```bash
  python start.py --public
  ```
  > [!WARNING]
  > Binding to `0.0.0.0` exposes the application to your local network. **Never expose the system publicly or on untrusted networks with real, unanonymized patient/case data** without authenticating reverse proxies.

### Advanced Usage

- **Developer Mode**: To run with Hot Module Replacement (Vite) for UI development:
  ```bash
  python start.py --dev
  ```
- **Manual Build**: If you prefer the legacy manual method:
  ```bash
  cd frontend && npm run build && cd ..
  python start.py
  ```

### Deployment Configuration
The system defaults to `H2L_SAFE_START=false` (Full RAG) in `start.py`. To run on low-resource machines, you can manually set `H2L_SAFE_START=true` to skip heavy model loading.
- `ENABLE_DENSE_RUNTIME=true` and `USE_RERANK=true` are enabled by default in `start.py` for maximum research fidelity.

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

## Typhoon 2.1 Gemma Runtime

The upstream `scb10x/typhoon2.1-gemma3-4b:latest` model contains a chat template
that Ollama's automatic llama-server parser cannot compile. Start Ollama with
the Go template renderer before selecting this model:

```bash
OLLAMA_GO_TEMPLATE=1 ollama serve
```

For an isolated comparison server that does not replace an Ollama app already
running on port 11434:

```bash
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_GO_TEMPLATE=1 ollama serve
LOCAL_LLM_BASE_URL=http://127.0.0.1:11435/v1 \
  .venv/bin/python scripts/compare_l2_models.py
```

This compatibility setting changes only template rendering. The model weights,
prompt, taxonomy, temperature, seed, and H2L scoring remain unchanged.

## Checks

```bash
cd frontend
npm run lint
npm run build
npm run smoke:cdp
```

`npm run smoke:cdp` expects the FastAPI app to be running at `http://127.0.0.1:8000/` and Chrome DevTools Protocol available on `127.0.0.1:9222`.
