# Design System — 6thSense

Created by `/design-consultation` on 2026-07-03. Read this before any visual or UI decision.

## Product Context
- **What:** tactile-hardware company for dexterous robotics. We sell the touch layer for robot learning: human capture gloves and custom robot skin.
- **Who:** teams collecting dexterous-manipulation data (glove buyers, most currently on Manus); dexterous-hand manufacturers (skin buyers).
- **Space:** robotics / embodied-AI hardware. Named competitor: Manus (mocap gloves, ~$2K+, no tactile).
- **Type:** marketing + product site (Vite/React SPA, dark hero already present).
- **Memorable thing:** *"well-made hardware that actually feels, half the price of the incumbent."* Every decision serves this.

## Narrative Spine — Glove → Skin
The site is a progression:
1. **The glove** — the human capture glove, tactile. Ships today, $1,000. The real, provable, buyable product. Start and stay here.
2. **The skin** — that sensing moved onto the robot. Custom tactile skin molded to a dexterous hand or gripper. The destination.

Read as: *capture touch on a human hand → transfer it to the robot.* Lead with the real, buyable glove; end at the payoff (robot skin).

**Retired — Nerve.** The per-joint "next version" glove, and all reserve / pre-order / waitlist intake, are removed. Rationale: an open waitlist for a next version dims the signal that the current glove is *for sale today*. Do not reintroduce a "coming soon" version, a reserve/pre-order flow, or the one-glove-two-states joint-reveal without explicit approval.

## Contact
There is **one intake** on the whole site: a **Contact Us** form at the bottom of the home page (`#contact`). It captures the contactor's details (name, email, organization) plus their message. Every product CTA links to it (`/#contact`). No per-product forms, no reserve/waitlist.

## Aesthetic Direction
- **Direction:** dark-cinematic product showcase + soft rounded editorial. Reference: the Evora EV-charger site (dark hero with rim-lit product, light rounded content sections, warm orange).
- **Decoration:** intentional — radial glow behind floating / rim-lit products, subtle grain, turntable rings. Restrained, never busy.
- **Mood:** a well-made scientific instrument that is also warm and human. Precision without coldness. Warm, not sci-fi cyan.

## Typography
Supersedes the prior Fraunces / Newsreader / Outfit editorial system.
- **Display / Hero:** General Sans (Fontshare), 600–700 — rounded geometric grotesque, warm and modern. Tight tracking (-0.02em) at large sizes.
- **Body:** General Sans, 400–500.
- **UI / labels / buttons:** General Sans, 500.
- **Data / spec numbers:** Geist Mono (Google Fonts), 400–500 — instrument-readout feel ("440 cells · 0.1–350 N · <1 ms · 200 Hz").
- **Loading:** Fontshare CSS for General Sans, Google Fonts for Geist Mono. Self-host both for production performance.
- **Scale (clamp, px):** hero clamp(44,6vw,74) · h2 clamp(30,4vw,46) · display-number 46 · intro clamp(22,2.6vw,32) · body 16–18 · label 11.5–14.
- A `google-fonts` MCP is installed (user scope) if alternatives ever need exploring.

## Color
- **Approach:** restrained — black + white + one warm orange. No other hues.
- **Accent:** `#F0612A` (warm orange). CTAs, dots, product rim-light, joint sensors.
- **Dark ground:** `#0e0d0a`; dark surfaces `#141009` / `#1c1810`. On-dark text `#f4f1ea`, muted `#a49c86`.
- **Light surfaces:** `#ffffff` / `#f7f4ee`. On-light text `#17150f`, muted `#6b6555`.
- **Backdrop** (the frame floats on it): warm radial `#f3ecdd → #cfc7b4`.
- **Hairlines:** on dark `rgba(255,255,255,.12)`, on light `rgba(20,18,12,.1)`.
- **Semantic (sparse):** success `#8fd08a`, error `#d9534f`.
- **Section rhythm:** alternate dark and light. Dark = hero + contact. Light = stats + products.

## Spacing
- **Base:** 8px. **Density:** comfortable.
- **Scale:** 2xs 2 · xs 4 · sm 8 · md 16 · lg 24 · xl 32 · 2xl 48 · 3xl 64.
- Section padding ~56px desktop, 40px vertical, 22px gutters mobile.

## Layout
- **Approach:** hybrid — editorial alternating rows for marketing/product, disciplined grid for stats/specs/forms.
- **Frame:** the whole page sits in a rounded frame (radius 30px) floating on the warm backdrop.
- **Max content width:** ~1160px.
- **Radius scale:** sm 8 · md 14 · card 24 · frame 30 · pill 999. Buttons are pills.
- **Product rows:** two columns, image/copy alternating sides; stack single-column below 780px.
- **Stats:** big display numbers, 4-up desktop / 2-up mobile, thin dividers.

## Motion
- **Approach:** intentional.
- Product **float** (translateY, 6–6.5s ease-in-out), slow **turntable ring** (28s linear), scroll reveals, and hover-tilt (~2KB vanilla-tilt).
- **Easing:** enter `cubic-bezier(.22,1,.36,1)`, spring `cubic-bezier(.34,1.56,.64,1)`.
- **Duration:** micro 80ms · short 180ms · medium 260ms · long 420ms.
- **All motion gated by `prefers-reduced-motion`.**

## Imagery Rules
- **Hardware honesty:** no AI-generated fake product shots (technical buyers spot them). Real photo knocked out on the glow stage for the glove; CAD turntable render for the robot skin.
- Hero glove knocked out, floating in orange rim-light.
- **True spin** needs 360° capture (glove) or CAD turntable (skin); a single knockout only floats, it doesn't rotate.
- **Full-bleed cinematic media band** (real capture footage) for atmosphere, like the reference's landscape clip.
- **NDA:** do not name Chestnut Robotics / Tether IA or the "Aero Hand" publicly until cleared; use "a dexterous hand."

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-03 | Dark-cinematic + rounded (Evora-style); General Sans + Geist Mono; orange `#F0612A`; Hand → Nerve → Skin spine; one-glove-two-states | `/design-consultation`; user-selected from the Evora reference video; supersedes the Fraunces / paper-editorial system |
| 2026-07-08 | **Retire Nerve** and the whole reserve/pre-order/waitlist idea; spine collapses to Glove → Skin; a single **Contact Us** form (name/email/org/message) at the bottom of the home page is the only intake; `leads` DB table collapsed to that one contact model (dropped `kind`/`product`) | User + advisor: a "next version" waitlist dims the signal that the current glove is for sale today |

## Reference Artifacts
- Approved wireframe (dark Evora-style): `~/.gstack/projects/alnosarus-6thSense/designs/product-page-20260703/` (see `evora.html`, `evora-fixed.png`).
- Companion design doc + eng review: `~/.gstack/projects/alnosarus-6thSense/alexnoh-product-pages-gloves-skin-rig-design-20260702-234503.md`.
