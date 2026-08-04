# 6thSense conference site audit

Audit date: 2026-08-04
Decision context: Ronak is sharing the site from the AI4 conference floor in Las Vegas, August 4–7. The target visit is a robotics buyer opening the URL on a phone immediately after meeting him.

## Executive verdict

The site is visually distinctive, but it is not ready for this conversion moment. A buyer is made to wait, infer the product, and scroll through a long thesis before seeing proof or a way to continue the conversation. Meanwhile, the product and SEO routes publish claims outside the approved boundary.

The immediate conference goal should be: in the first phone viewport, remind the visitor what Ronak showed them, name **Eye2**, state only the defensible **30 fps** specification, show real evidence, and offer one low-friction next step. The present site does none of those things in the first screen.

No implementation changes were made as part of this audit. Even small copy removals are spread across live, legacy, and prerendered routes and need to be handled together to avoid leaving contradictory customer-facing claims behind.

## What the site currently claims

### Homepage (`/`)

The homepage claims that:

- 6thSense makes tactile capture hardware for dexterous robots.
- Vision identifies objects, while pressure/force determines how to grip them.
- 6thSense can “train force from touch” and help robots master precision.
- Its hardware supports a collect → synchronize → label → validate → ship workflow.
- Its rig captures synchronized tactile and egocentric video.
- Research associated with Amazon Robotics, Columbia, Stanford, and Meta supports the value of touch; the strongest numeric statement is “Vision alone solves 30% of manipulation tasks. Touch raises it to 90%.”
- The company is backed by Y Combinator, NVIDIA Inception, the University of Chicago, and Georgia Tech.

What is defensible from the approved constraints:

- The broad positioning around egocentric/tactile capture and synchronized video/touch is directionally compatible with Eye2.
- “30 fps” is defensible, but it is not stated anywhere on the homepage.
- “Pressure proxies” and contact timing are safer concepts than calibrated force. The current homepage instead repeatedly collapses touch, pressure, and force into one another: “Force is the invisible variable,” “train force from touch,” and “Every touch, recorded as force” on the product page. Those statements should not ship without evidence that the system measures ground-truth force.
- The research cards provide logos and short attributions but no links, paper titles, methodology, or qualification. The 30% → 90% statement is particularly risky because the page presents it as a general manipulation result. It cannot be defended from this repository and should be removed or linked to a precise source with accurate scope.
- “Backed by” combines an investor with programs/universities. Unless all four organizations have explicitly approved that relationship label, use a more exact label per organization.

### Product route (`/products`)

The default product page offers three things: Skin, Eye2, and Hand. It presents calls to “Talk to us,” “Request a demo,” and “Build with us.” That conflicts with the conference constraint that **Eye2 is the only product to offer**.

The page publishes these numeric or technical claims:

- Skin: 440 tactile channels, 0.01 N resolution, <1 ms response, 200 Hz sustained.
- Eye2: 4000×1200 stereo capture, 30 fps global shutter, wireless Wi-Fi streaming, onboard compute, and microSD.
- Hand: 1:1 molded fit, any surface, and per-task touch layout.

Only **Eye2 at 30 fps** is inside the approved claim boundary. Remove the other Eye2 specs and do not publish glove/skin/hand specifications in the conference offer. In particular, “onboard compute + microSD” is an onboard capability claim and must go; source comments also assert onboard H.264 even though it is not rendered.

The legacy `/products?v1` route is still publicly reachable and is worse: it labels Skin and Eye2 “Available now,” describes the glove’s detailed specs, and offers custom Hand. A query parameter is not an access control. Buyers, crawlers, old links, and screenshots can still expose it.

### SEO product routes (`/product`, `/product/gloves`, `/product/skin`, `/product/rig`)

These routes are public, included in the sitemap, and build-prerendered, so their claims matter even though the primary navigation does not link to them.

They assert a model-ready synchronized capture stack, calibrated glove/skin signals, detailed glove performance, stereo depth performance, sensor size and pixel pitch, Wi-Fi, onboard compute, and microSD. The rig page’s only approved spec is 30 fps. References to depth capability/performance, 4000×1200, sensor details, wireless behavior, onboard compute, and microSD must be removed. The glove and skin numeric claims are outside the Eye2-only boundary.

### `eye1` and prohibited-claim inventory

- No rendered customer copy names Eye1.
- `frontend/src/pages/ProductsV2.jsx` does name Eye1 in source comments and records its 60 fps/USB/IMU details. Since Eye1 is discontinued and must never be offered, remove this product history from the marketing codebase; it creates an easy copy/paste regression path.
- The same comments assert Eye2 onboard H.264. Remove that assertion too.
- No customer-facing battery-hours, weight, dimensions, FCC/CE/IP certification, or MTBF claims were found.
- Depth is claimed repeatedly in `frontend/src/seo/pages.js` and in currently unused narrative data in `frontend/src/homeNarrative.js`. Remove it from customer-facing/prerendered Eye2 copy and from reusable marketing content unless a separately attached depth camera is being described with explicit scope.

### Brand-mark compliance

The required mark is **five brown `#532a0f` dots and one green `#677126` dot**. The animated opener and dormant finale-dot styles instead use brown `#4a2418` and green `#7a8f3a`, with additional green animation colors. The navigation applies a white filter to the raster logo, so the visible nav mark is not the required two-color mark either. This is a brand-compliance defect, not a subjective palette preference.

## Mobile-first conversion audit

The phone audit used the production build at a 390px viewport. The build succeeds.

- **The visitor waits 3.8 seconds before seeing the site.** A first visit in every new tab gets a full-screen, non-skippable logo animation and locked scrolling. Conference-floor attention is too scarce for a decorative delay.
- **The first screen does not say Eye2, explain what can be bought, show a proof point, or contain a CTA.** It opens with “A robot can recognize a strawberry…” over a glove. This is category education, not meeting follow-up.
- **The page is approximately 7,934px tall at 390px, about 9.4 phone screens.** The contact form is the final beat after a 400vh stage, a 200vh mobile research timeline, and a 340vh second stage. Most referred visitors will never reach it.
- **The homepage eagerly transfers roughly 2.0MB before the visitor elects to play video.** About 1.74MB is five full-resolution glove frames. The mobile video decision is sensible (posters and tap-to-play), but the hero image strategy undermines it.
- **Meaning depends on scroll-scrub state.** Copy swaps while a sticky canvas animates. Fast thumb scrolling, interrupted attention, browser UI resizing, or an older phone can turn the story into fragments. A conference follow-up page should preserve a complete offer without requiring precise scroll behavior.
- **Proof arrives late and is hard to inspect.** The actual demo is in the second sticky stage. Both demo videos are desktop-composited 16:9 footage stacked into a phone viewport; native fullscreen controls help, but the buyer first has to discover the beat.
- **The conversion form is too demanding for this context.** It requires name, work email, a written project description, and consent. After an in-person meeting, a buyer should be able to book/follow up with minimal typing. There is no calendar, “email Ronak,” or compact demo request on the first screen.
- **The nav prioritizes low-conversion destinations.** Products, People, and Partner login are behind the mobile menu; there is no persistent “Request demo” action. Partner login is irrelevant to a new conference lead.
- **`/products` is more scannable but still not a solution.** Eye2 is the second of three tall scenes, and its CTA jumps to `/#contact`, forcing the visitor into the homepage and relying on a deep anchor inside a scroll-driven experience. It also leads with unsupported specs and makes other products look available.
- **The page title is broad rather than meeting-specific.** “The touch layer for dexterous robots” does not help a buyer reconnect the site with Eye2 or Ronak’s AI4 conversation.

## Single weakest thing about the first screen

**It never answers “what did Ronak just show me, and what should I do next?”**

After a 3.8-second interruption, the visitor sees a strawberry thought experiment and a glove animation. Eye2 is unnamed, 30 fps is absent, there is no concrete evidence, and there is no CTA. A buyer cannot distinguish a purchasable egocentric camera from a research vision, understand the status, or continue the conversation without navigating or scrolling.

## Ranked fixes

Effort assumes one frontend engineer with copy/claim approvals available. “Conference blocker” means fix before Ronak sends the URL broadly.

| Rank | Fix | Why it matters | Rough effort |
|---:|---|---|---|
| 1 | **Conference blocker: enforce the claim boundary everywhere.** Make Eye2 the only offered product; retain only 30 fps as a spec. Remove all other Eye2 specs, force-measurement language, unsupported research numbers, glove/skin/Hand offers and specs, and depth-performance claims across `/products`, `?v1`, SEO/prerender content, sitemap-linked pages, metadata, and reusable narrative data. Remove Eye1 and onboard-H.264 source comments. | Prevents Ronak from making an indefensible or discontinued offer from the page he is actively sharing. Partial cleanup is insufficient because prerender and legacy routes remain public. | 0.5–1 day, including claim sweep and build verification |
| 2 | **Conference blocker: replace the first-screen message with a complete Eye2 offer.** Above the fold: Eye2 name, buyer outcome, “30 fps,” a real product/demo visual, and one primary “Request an Eye2 demo” action. Preserve the existing visual system; this is message hierarchy, not a redesign. | Fixes the single largest conversion failure: the referred buyer immediately recognizes the product and next step. | 0.5 day with approved copy/assets |
| 3 | **Remove or bypass the 3.8-second opener for conference traffic, especially mobile.** The first paint should reveal the offer immediately. | Recovers the most valuable seconds of a high-intent visit and eliminates a non-skippable barrier. | 1–2 hours |
| 4 | **Put a low-friction conversion action in the first viewport and nav.** Use a short Eye2 demo request or direct meeting/email action; do not require a project essay. Keep the longer qualification form as a secondary path. | Lets a buyer act while Ronak and the conversation are still fresh. | 0.5 day; calendar/CRM integration may add 0.5 day |
| 5 | **Make proof phone-native and immediate.** Place a short, tap-to-play Eye2 demonstration or clear poster beside the offer, with a one-line caption stating what is real. Avoid tiny dashboard panes as the only evidence. | Robotics buyers need to see working hardware/data before accepting category claims. | 0.5–1 day if a suitable clip exists; 1–2 days if it must be recut |
| 6 | **Collapse the conference journey.** Provide a direct Eye2 landing path that reaches proof and conversion in roughly 2–3 phone screens; keep the long editorial story as optional exploration. Ensure all conference QR codes and shared links use it. | The current ~9.4-screen scrub journey is poorly matched to a distracted referral visit. | 1 day implementation plus routing/QR check |
| 7 | **Reduce first-load mobile weight.** Serve appropriately sized first-screen frames, load only the initial/adjacent frame until interaction, and defer the rest. Set a mobile first-load budget and test on throttled cellular. | The measured ~2.0MB initial load is avoidable; five hero frames account for most of it and compete with the moment of intent. | 0.5–1 day |
| 8 | **Fix the brand mark wherever it appears.** Use exactly five `#532a0f` dots and one `#677126` dot; remove alternate animation colors and the nav white-out treatment unless an explicitly approved monochrome variant exists. | Enforces the supplied identity and stops inconsistent marks from appearing in the same visit. | 1–2 hours plus visual regression check |
| 9 | **Turn evidence labels into auditable proof.** Link exact papers/case studies, scope every statistic, and distinguish investor, accelerator/program, university, and customer relationships. If permission or sourcing is unavailable, remove the logo/claim. | Sophisticated buyers will challenge broad claims; precise provenance builds more trust than logo adjacency. | 0.5 day once sources/permissions are supplied |
| 10 | **Instrument the conference funnel.** Track first-screen CTA taps, demo plays, form starts/completions, and source/QR campaign. Confirm lead delivery on a real phone before the floor opens. | Makes the Aug 4–7 traffic actionable and reveals failures while Ronak can still change the link or pitch. | 0.5 day plus analytics access |

## Verification performed

- Read the homepage, products, public SEO/prerender manifests, nav, lead form, mobile CSS, animation, and relevant source comments.
- Ran a case-insensitive repository sweep for Eye1/Eye2 and all prohibited claim categories.
- Ran `npm ci` and `npm run build` in `frontend/`; production build passed.
- Rendered `/` and `/products` in headless Chromium at a 390px mobile viewport and inspected first-screen content, page height, routes, and transfer sizes.
