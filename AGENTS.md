# 6thSense — agent memory

Durable workspace facts and repeated preferences from sessions. **No secrets or API keys.** Omit transient troubleshooting.

## Layout

- **`ml/`:** Training and data prep (`experiment.py`, `train_robust.py`, `prepare_data.py`, `research.py`, `sanity_check.py`). Paths and datasets come from **`config/senseprobe.defaults.yaml`** + env (`SENSEPROBE_*`); see `ml/senseprobe_config.py`.
- **`data/`:** Raw/processed data (mostly gitignored); conventions in `data/README.md`.
- **`frontend/`:** Public narrative site — **Vite + React**. The primary hero is a **scroll-scrubbed 2D canvas “rig tour”** (glove frame sequence + sticky stage) using **Framer Motion**, **lucide-react**, with frame assets under **`frontend/public/hero/glove/`** (`frame-00X.webp`) plus an HTML5 `<video>` demo clip in `frontend/public/` — not a WebGL/Three.js hero.
- **`backend/`:** Minimal FastAPI service (health, future API).
- **`.planning/`:** GSD-style artifacts (local; often untracked) — `ROADMAP.md`, `REQUIREMENTS.md`, `STATE.md`, `PROJECT.md`, phase folders.

## Paths and shell

- Repo path includes bracket segments (`[00] GitHub/[01] Active/...`). **Always quote** paths in `cd`, `git`, and tool args.

## Design and quality bar

- For landing and marketing surfaces, follow **frontend-design** and **ui-ux-pro-max** (repo: `.cursor/skills/`). User expects **product-grade** visual and interaction quality (editorial type, scroll/3D immersion), not a minimal demo.
- Official skill sources matter; do not replace with ad-hoc condensed copies without syncing from the plugin originals.

## Planning and delivery

- User wants **GSD-aligned** delivery for major landing work: phased roadmap, explicit narrative (e.g. PNS/CNS/Fusion, proof points), and **verification** (e.g. `npm run build` in `frontend/`) before claiming completion.
- Prefer **executing** installs, builds, and git operations in-session rather than only telling the user to run commands.

## Git

- **Default branch:** `main`. If `gh repo create … --remote=origin` fails because **`origin` already exists**, remove or repoint `origin` first, then push.

## Learned User Preferences

- For major landing or homepage work, sequence decisions before coding: lock product story and page structure, then visual and motion systems, then implementation—avoid jumping straight into implementation without that alignment.
- Use scroll-driven, premium product storytelling (reference: https://wisprflow.ai) as an interaction-depth benchmark alongside **frontend-design** and **ui-ux-pro-max**.
- For in-editor review in Cursor, serve the production build with **`npm run build`** then **`npm run preview`** in **`frontend/`** (default preview port **4173**; dev/preview may use another port if the default is in use).
- Prefer **device-forward hero composition**: the **scroll-scrubbed hardware (glove) tour** and its canvas should read as the primary focal point of the viewport, with wordmark and CTAs layered over it—not a side column layout that competes with the hero.
- When building **cards, pipeline tiles, or overlays** on the landing, ensure **referenced CSS variables exist** (e.g. paper/surface tokens like `--paper-1`); **undefined custom properties read as transparent** and can let the dark hero/canvas show through, which looks like stray “hardware” in the background—also mind **stacking context** (`z-index` / `isolation`) between `#story` and `.page-after-hero`.
- When iterating on the **frontend or landing**, keep **`npm run dev`** or **`npm run preview`** running and share the URL/port so the page can be reviewed in the browser or Cursor preview—not only code edits without a live build.
- On **long scroll landings**, keep **backgrounds, gradients, and palette** feeling like one system across sections; avoid abrupt tonal jumps and muddy or banded gradients that break the editorial look.
- **Landing color and navigation** are user-led; implementation should follow the locked **SASI Visual Identity** via **`frontend/src/styles.css`** tokens (`--sasi-1`…`--sasi-5` and semantic aliases such as `--ink` / `--accent`), not scattered one-off colors in components.
- **Primary navigation** should behave in a scroll-aware way where appropriate: full bar near the top, **hide on scroll-down**, **compact centered “bubble” on scroll-up** (see `useRevealNav.js`), with **`prefers-reduced-motion`** falling back to a stable bar.
- For **premium, non-generic layouts**, use **subtle skew, perspective, and angled frames** sparingly and consistently; keep **readable text upright** while containers or supporting shapes carry the attitude.
- Prefer **scroll-emergent** affordances (progress, section cues) over **always-on side chrome** when both could achieve the same goal, so the interface feels tied to the scroll journey.

## Learned Workspace Facts

- **Brand / company name:** **6thSense** (public-facing product and landing copy).
- Large raw datasets and generated ML artifacts belong under **`data/`** with strict **`.gitignore`** coverage; accidental tracking inflates uncommitted line counts and should be corrected immediately.
- **Public landing palette (SASI Visual Identity):** five swatches—**#262312**, **#736A3C**, **#A69A60**, **#BFB68A**, **#592202** (olive–sand ramp plus rust accent). RGBA/HSLA exports are mirrored as CSS variables in **`frontend/src/styles.css`** for parity with design tooling.
- **Hardware-tour frame assets** (the scroll-scrubbed glove sequence) live under **`frontend/public/hero/glove/`** as `frame-00X.webp`; the hero also uses an HTML5 `<video>` demo clip in `frontend/public/`. (The older `frontend/public/scroll-video/` path no longer exists.)
- The **marketing page** after the hero is composed to **coexist with** the cofounder rig tour (single `#story` hero, then `.page-after-hero` sections)—integrate new sections without breaking scroll-scrub progress or nav section IDs.
