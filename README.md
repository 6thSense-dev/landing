> 🧠 **Part of the 6thSense nervous system** — marketing site + customer portal.
> Full map & what-every-repo-is: **[atlas](https://github.com/6thSense-dev/atlas)**.

# 6thSense

**6thSense** builds **custom tactile egocentric datasets for robotics teams**: hardware, synchronized multimodal capture, calibration, quality control, and **model-ready packaged data** for contact-rich robot learning—not just raw sensors or generic recording tools.

This repository hosts the **6thSense** product site (public marketing page + partner portal) and its minimal supporting API.

## Monorepo layout

| Area | Path |
|------|------|
| Public site (Vite + React) | `frontend/` |
| Minimal API (FastAPI) | `backend/` |

## Backend

```bash
cd backend && pip install -r ../requirements-backend.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`GET /health` returns `{"status":"ok"}`. See `backend/README.md`.

For Collector operations, see [clean footage, combined viewing, and contributor estimates](docs/OPS-CLEAN.md) and the [Raw processing queue](backend/README.md#raw-processing-queue).
For contracted footage outside individual payouts, see [business source attribution](docs/OPS-BUSINESS-SOURCES.md).
For Sieve's Clean-only MP4, metadata and calibration handoff and its temporary hours/diversity dashboard, see [Sieve collection and inheritance](docs/SIEVE-CLEAN-INHERITANCE.md).
For audited bookkeeping of payments made outside the payout workflow, see [external payment records](docs/EXTERNAL-PAYMENT-RECORDS.md).
For Korean contributor signup through the interim Google Form contract register, secure website activation and verified camera handover, see the [Form register release guide](docs/contributors/google-form-register.md). It records deployment checks and the retention work that remains operational.
For verified mobile accounts, supervised camera requests and bank-recipient review, see the [contributor mobile pilot](docs/CONTRIBUTOR-MOBILE-PILOT.md). The pilot retains manual SD-card upload and requires published agreements before camera or bank registration.
For account-deletion receipts, operator fulfillment, and migration/rollback requirements, see the [contributor deletion release contract](docs/CONTRIBUTOR-DELETION.md).

## Frontend

The public site is a **React + Vite** app in `frontend/`. The hero is a **scroll-scrubbed 2D canvas "rig tour"** — a glove frame sequence (`frontend/public/hero/glove/frame-00X.webp`) painted to a canvas as you scroll — alongside an HTML5 `<video>` demo clip. It uses **Framer Motion** (`framer-motion`) for motion and **lucide-react** for icons; **react-router-dom** routes a lazy-loaded partner portal at `/login` and `/portal/*`. It also uses **Three.js** (`three`) for WebGL 3D turntable views (hand, glove, and eye2 models in `frontend/src/lib/`). Self-hosted fonts live in `frontend/public/fonts/` (served as `woff2`, with `.ttf` fallback) and are declared in `frontend/index.html` + `frontend/src/scroll-hero.css`, plus a Google Fonts request in `index.html`.

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 4173
```

Production build: `cd frontend && npm run build` (output in `frontend/dist/`). The build also injects a crawlable SEO prerender block via `frontend/scripts/seoPrerenderPlugin.js`.

In production the built `dist/` is served by **Caddy** (compression, immutable `/assets/*` caching, security headers, SPA fallback) — see `frontend/Dockerfile` + `frontend/Caddyfile` — and deployed on **Railway** (`frontend/railway.toml`).

Core entry points: `frontend/src/main.jsx` (router) · `App.jsx` (public site) · `ScrollHero.jsx` → `ScrollStage.jsx` / `HeroStageOne.jsx` / `HeroStageTwo.jsx` / `QuoteTimeline.jsx` / `TactileField.jsx` (hero) · `homeNarrative.js` (copy + SEO source) · `styles.css` · `scroll-hero.css` · `src/portal/` (partner portal).
