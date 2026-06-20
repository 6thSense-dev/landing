# 6thSense

**6thSense** builds **custom tactile egocentric datasets for robotics teams**: hardware, synchronized multimodal capture, calibration, quality control, and **model-ready packaged data** for contact-rich robot learning—not just raw sensors or generic recording tools.

This repository hosts the **6thSense** product site and supporting tooling. Internal ML/config paths may still use legacy `senseprobe` filenames and `SENSEPROBE_*` environment variables for continuity with existing experiments; see **Data & ML configuration** below.

## Monorepo layout

| Area | Path |
|------|------|
| Public site (Vite + React) | `frontend/` |
| Minimal API (FastAPI) | `backend/` |
| Training / data prep | `ml/` |
| Data bootstrap | `scripts/setup_data.py` |
| Paths, datasets, model run lists | `config/senseprobe.defaults.yaml` |

## ML research (ultrasound stiffness)

The `ml/` package includes experiments that probe whether **B-mode ultrasound** images contain recoverable stiffness signals using ML (paired B-mode + elastography data; classification and regression with models such as ResNet18 and EfficientNet-B0).

### Goal

Can we predict tissue stiffness (kPa) from standard ultrasound images alone?

### Evaluation targets (heuristic)

- Classification: accuracy > 60% suggests recoverable signal
- Regression: R² > 0.3 promising; R² > 0.5 very promising

## Data & ML configuration

- **`data/README.md`** — where to place zips, extraction, and dataset catalog links.
- **`config/senseprobe.defaults.yaml`** — dataset registry (`datasets:`), roots (`paths:`), and which models `ml/research.py` / `ml/experiment.py` run (`training:`). Override with **`SENSEPROBE_CONFIG`**, **`SENSEPROBE_DATASET`**, **`SENSEPROBE_DATA_ROOT`**, **`SENSEPROBE_RESULTS_DIR`**, **`SENSEPROBE_MODELS_DIR`** (see `.env.example`).

Typical flow:

```bash
python scripts/setup_data.py
python ml/prepare_data.py
python ml/experiment.py
```

Use `--dataset <id>` on ML scripts to switch entries in the config without editing files.

## Backend

```bash
cd backend && pip install -r ../requirements-backend.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`GET /health` returns `{"status":"ok"}`. See `backend/README.md`.

## Frontend

The public site is a **React + Vite** app in `frontend/`. The hero is a **scroll-scrubbed 2D canvas "rig tour"** — a glove frame sequence (`frontend/public/hero/glove/frame-00X.webp`) painted to a canvas as you scroll — alongside an HTML5 `<video>` demo clip. It uses **Framer Motion** (`framer-motion`) for motion and **lucide-react** for icons; **react-router-dom** routes a lazy-loaded partner portal at `/login` and `/portal/*`. There is **no Three.js / WebGL** dependency. Self-hosted fonts live in `frontend/public/fonts/` (served as `woff2`, with `.ttf` fallback) and are declared in `frontend/index.html` + `frontend/src/scroll-hero.css`, plus a Google Fonts request in `index.html`.

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 4173
```

Production build: `cd frontend && npm run build` (output in `frontend/dist/`). The build also injects a crawlable SEO prerender block via `frontend/scripts/seoPrerenderPlugin.js`.

In production the built `dist/` is served by **Caddy** (compression, immutable `/assets/*` caching, security headers, SPA fallback) — see `frontend/Dockerfile` + `frontend/Caddyfile` — and deployed on **Railway** (`frontend/railway.toml`).

Core entry points: `frontend/src/main.jsx` (router) · `App.jsx` (public site) · `ScrollHero.jsx` → `ScrollStage.jsx` / `HeroStageOne.jsx` / `HeroStageTwo.jsx` / `QuoteTimeline.jsx` / `TactileField.jsx` (hero) · `homeNarrative.js` (copy + SEO source) · `styles.css` · `scroll-hero.css` · `src/portal/` (partner portal).
