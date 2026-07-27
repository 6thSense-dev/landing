import { useCallback, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";

import SiteNav from "../SiteNav.jsx";
import { useRevealNav } from "../useRevealNav.js";
import ParticleImage from "../lib/ParticleImage.jsx";
import "../evora-home.css";
import "./people-reveal.css";

/**
 * 6thSense /people — navbar + a particle team photo on black. The YC board stays
 * as fixed particles; focus a person and their dots resolve into their real
 * (translucent, feathered) photo while the others fade, with a pure-text blurb
 * beside them.
 *
 * Discoverability: the reveal used to be reachable only by blindly hovering an
 * invisible band, which nobody guessed and touch devices could not do at all.
 * Now a VISIBLE person list (same thin-rule/orange-active language as the
 * /products side-nav) drives the same reveal. Click/tap is the primary,
 * reliable mechanism; hover is a pointer-only preview on top of it.
 *
 * Below 1024px the page is a normal scrolling document — canvas, list, then the
 * bio in flow — instead of a fixed 100vh stage with position:fixed children,
 * which was unusable on a phone.
 *
 * PEOPLE is left → right as they stand. All four positions were verified against
 * the source photo and confirmed by Ronak on 2026-07-26 — this is not a guess.
 * The figures occupy, as a fraction of image width:
 *
 *   Alex 0.057–0.264 | Matt 0.296–0.443 | James 0.45–0.643 | Ronak 0.668–0.95
 *
 * against BANDS 0 / 0.28 / 0.44 / 0.63 / 1, so every band's dominant figure is
 * unambiguous with no off-by-one. Changing BANDS or reordering PEOPLE breaks the
 * mapping; if team.webp is ever replaced, re-derive those spans and re-verify
 * rather than assuming the old ones still hold.
 */
const BANDS = [0, 0.28, 0.44, 0.63, 1]; // 4 people; index 4 = board
const BOARD_TOP = 0.6;
const COMPACT_QUERY = "(max-width: 1023px)";

// The desktop blurb's live region is always mounted; when nobody is revealed it
// collapses to nothing rather than unmounting (see m12 note at the render site).
const BLURB_SHELL_IDLE = {
  position: "fixed",
  top: 0,
  left: 0,
  width: 0,
  height: 0,
  overflow: "hidden",
  pointerEvents: "none",
};
const BLURB_INNER = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  width: "100%",
  height: "100%",
};

const BLURB_FONT = "'General Sans', system-ui, sans-serif";
const LINE_SCALE = 0.6; // info-line size relative to the name size
const GAP_SCALE = 1.0; // name→info gap relative to the name size
const NAME_LINE_HEIGHT = 1.2;
const LINE_LINE_HEIGHT = 1.75;
const MIN_NAME_SIZE = 26;
const MAX_NAME_SIZE = 92;
const MIN_NAME_SIZE_WRAPPED = 18; // narrow stages: shrink further before we'd rather wrap than truncate

let measureCtx = null;
function textWidth(text, px, weight) {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  measureCtx.font = `${weight} ${px}px ${BLURB_FONT}`;
  return measureCtx.measureText(text).width;
}

function countWrappedRows(text, px, weight, maxWidth) {
  const words = text.split(" ");
  const spaceWidth = textWidth(" ", px, weight);
  let rows = 1;
  let rowWidth = 0;
  for (const word of words) {
    const w = textWidth(word, px, weight);
    if (rowWidth === 0) {
      rowWidth = w;
    } else if (rowWidth + spaceWidth + w <= maxWidth) {
      rowWidth += spaceWidth + w;
    } else {
      rows++;
      rowWidth = w;
    }
  }
  return rows;
}

// Picks the largest name/info font size that lets every line sit on a single
// line within the available box — so revealing someone never produces an awkward
// mid-word wrap. Desktop only; the compact layout uses plain CSS type.
function fitBlurbSize(person, availWidth, availHeight) {
  const ref = 100;
  const nameWidthAtRef = textWidth(person.name, ref, 600);
  const lineWidthAtRef = Math.max(
    0,
    ...person.lines.map((l) => textWidth(l, ref * LINE_SCALE, 400))
  );
  const widestAtRef = Math.max(nameWidthAtRef, lineWidthAtRef);
  const byWidth = widestAtRef > 0 ? (availWidth * 0.92 * ref) / widestAtRef : MAX_NAME_SIZE;

  const heightCoeff = NAME_LINE_HEIGHT + GAP_SCALE + person.lines.length * LINE_SCALE * LINE_LINE_HEIGHT;
  const byHeight = (availHeight * 0.94) / heightCoeff;

  const nameSize = Math.min(MAX_NAME_SIZE, Math.max(MIN_NAME_SIZE, Math.min(byWidth, byHeight)));
  return { nameSize, lineSize: nameSize * LINE_SCALE, gap: nameSize * GAP_SCALE };
}

// Narrow stages (small laptop windows): the empty space beside a person isn't
// wide enough to fit the longer bio lines on one row, so simulate the real
// word-wrap at each candidate size and shrink until the wrapped block fits the
// height — rather than truncating with an ellipsis.
function fitBlurbSizeWrapped(person, availWidth, availHeight) {
  const width = availWidth * 0.96;
  let nameSize = MAX_NAME_SIZE;
  while (nameSize > MIN_NAME_SIZE_WRAPPED) {
    const lineSize = nameSize * LINE_SCALE;
    const nameRows = countWrappedRows(person.name, nameSize, 600, width);
    const lineRows = person.lines.reduce((sum, l) => sum + countWrappedRows(l, lineSize, 400, width), 0);
    const height =
      nameSize * NAME_LINE_HEIGHT * nameRows +
      nameSize * GAP_SCALE +
      lineRows * lineSize * LINE_LINE_HEIGHT;
    if (height <= availHeight * 0.96) break;
    nameSize -= 2;
  }
  nameSize = Math.max(MIN_NAME_SIZE_WRAPPED, nameSize);
  return { nameSize, lineSize: nameSize * LINE_SCALE, gap: nameSize * GAP_SCALE };
}

/**
 * Approved copy. Editing it is a LAYOUT change, not just a copy change.
 *
 * Every bio line adds ~34px to the compact document, which raises the maximum
 * scroll offset, which eats the clearance that keeps page furniture out from
 * under the fixed nav pill. Measured against a production build, clearance at
 * max scroll (positive = clear of the pill):
 *
 *              lines   360x740 hint   390x844 h1   768x1024 h1
 *   3 lines      3      +12.0          +6.2         +11.4
 *   4 lines      4      +12.0          +5.2          +3.4   <- James today
 *   5 lines      5      -22.0          -29.8        -31.6   <- all three break
 *
 * So a FIFTH line on anyone pushes the affordance line ("TAP A NAME TO REVEAL
 * THEM") under the pill at 360x740, and that line is the whole reason this page
 * was reworked — see the scroll effect below. The heading is deliberately
 * sacrificial and may go under; the hint may not.
 *
 * If a fifth line is ever needed, buy back ~34px BELOW the hint at that
 * breakpoint (stage height, roster row height, bio spacing — not padding-top,
 * which cancels out) and re-measure, rather than assuming it still fits.
 */
const PEOPLE = [
  {
    name: "Alex Hyungwoo Noh",
    lines: [
      "Corporate scholarship from Samsung at 18",
      "Prev. tank driver & mechanic",
      "CS & Economics, UChicago",
    ],
  },
  {
    name: "Matt Wulff",
    lines: [
      "Vision-Guided Robotics at Tesla at 20",
      "Tactile Data Capture at Mecka AI",
      "First company at 16; builds rockets",
    ],
  },
  {
    name: "James Baek",
    lines: [
      "Founding engineer at Ibebu (Series C)",
      "Built Korea's first telemedicine product",
      "$50K+ MRR community; six-figure exit",
      "BME, Georgia Tech",
    ],
  },
  {
    name: "Ronak Agarwal",
    lines: [
      "Engineer at DoorDash & Amazon",
      "Delivered chickens faster with robots at Chick-fil-A",
      "CS & Economics, Georgia Tech",
    ],
  },
];

function useIsCompact() {
  const [compact, setCompact] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(COMPACT_QUERY).matches : false
  );
  useEffect(() => {
    const mq = window.matchMedia(COMPACT_QUERY);
    const onChange = (e) => setCompact(e.matches);
    mq.addEventListener("change", onChange);
    setCompact(mq.matches);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return compact;
}

/** The visible list of people — the affordance the page was missing. */
function Roster({ people, active, pinned, onSelect, onHover }) {
  return (
    // pointerenter/leave rather than mouseenter/leave: iOS Safari can fire a
    // synthetic mouseenter after touchend, which would leave a stale hover
    // preview pinned on a touch device. pointerType lets us reject that at the JS
    // level, where the CSS `(hover: hover)` guard cannot reach.
    <ul
      className="pv-roster"
      onPointerLeave={(e) => {
        if (e.pointerType === "touch") return;
        onHover(null);
      }}
    >
      {people.map((p, i) => (
        <li key={p.name}>
          <button
            type="button"
            className={`pv-item${active === i ? " is-active" : ""}${
              active == null && i === 0 ? " is-resting-hint" : ""
            }`}
            data-person-btn={i}
            aria-pressed={pinned === i}
            aria-controls="pv-bio"
            onClick={() => onSelect(pinned === i ? null : i)}
            onPointerEnter={(e) => {
              if (e.pointerType === "touch") return;
              onHover(i);
            }}
            onFocus={() => onHover(i)}
            onBlur={() => onHover(null)}
          >
            <i aria-hidden="true" />
            <span className="pv-item-name">{p.name}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function PeoplePage() {
  const bioRef = useRef(null);
  const headingRef = useRef(null);
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });
  const compact = useIsCompact();
  const [pinned, setPinned] = useState(null); // click/tap/keyboard selection
  const [hovered, setHovered] = useState(null); // pointer-device preview only
  const [geo, setGeo] = useState(null); // { anchors, stage } from the canvas, viewport space

  // A hover preview wins while the pointer is on someone; otherwise the pinned
  // selection stands. Touch never sets `hovered`, so tap alone always works.
  const active = hovered != null ? hovered : pinned;
  const person = active != null ? PEOPLE[active] : null;

  useEffect(() => {
    const prev = document.title;
    document.title = "People — 6thSense";
    const prevBg = document.body.style.background;
    document.body.style.background = "#050506";
    return () => {
      document.title = prev;
      document.body.style.background = prevBg;
    };
  }, []);

  // Escape clears the selection from anywhere on the page.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      setPinned(null);
      setHovered(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onSelect = useCallback((i) => {
    setPinned(i);
    setHovered(null);
  }, []);

  // Compact layout: the bio sits below the list, so a selection near the bottom
  // of the screen can land off-frame. Scroll the minimum needed to fix that.
  //
  // This used to carry a cap that bounded the scroll so the heading stayed clear
  // of the fixed nav pill. The cap is gone because it solved the wrong half of
  // the problem: it only limits PROGRAMMATIC scrolling, and a reader can always
  // drag to the bottom themselves, at which point the cap is irrelevant. What
  // actually protects the affordance line is a LAYOUT bound — the compact column
  // is short enough that the document's maximum scroll offset stays under
  // (hint top − nav bottom), so no scroll of any origin can hide it. See the
  // phone block in people-reveal.css.
  //
  // Note also that extra top padding could never have fixed this: padding grows
  // the document and the max scroll offset by the same amount, so where the top
  // of the page lands after scrolling to the bottom is invariant.
  // The heading has two clean resting states against the (opaque) nav pill: fully
  // below it, or fully tucked behind it. In between, its ascenders get sliced by
  // the pill's lower edge — the amputated look originally reported. A manual
  // scroll can always stop mid-window and that is just normal scroll-under, but
  // where the AUTOMATIC scroll lands is ours to choose, so land on a clean state:
  // if the minimum scroll would stop mid-slice, and going all the way to the
  // bottom tucks the heading cleanly, go there instead. Scrolling to the bottom
  // always leaves the bio fully visible, so this costs nothing.
  // Everything below is in ABSOLUTE document coordinates, never relative to the
  // current scroll offset, so the effect is idempotent. Measuring relatively made
  // it order-dependent: a second invocation (StrictMode double-invokes in dev, and
  // any re-run with the page already scrolled does the same in production) would
  // recompute from the moved page and undo its own snap.
  useEffect(() => {
    if (!compact || pinned == null || !bioRef.current) return;
    const sy = window.scrollY;
    const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const bioBottomAbs = bioRef.current.getBoundingClientRect().bottom + sy;
    let target = Math.max(0, Math.min(Math.ceil(bioBottomAbs - window.innerHeight + 8), max));

    const head = headingRef.current;
    const nav = document.querySelector('header[role="banner"]')?.getBoundingClientRect();
    if (head && nav && max - target <= 140) {
      const box = head.getBoundingClientRect();
      const topAbs = box.top + sy;
      const bottomAbs = box.bottom + sy;
      // Clean means fully below the pill, or fully tucked behind it. Anything
      // between slices the heading's ascenders on the pill's lower edge.
      //
      // EPS matters more than it looks: at max scroll the heading lands flush
      // with the pill's lower edge to within 0.016px, and a strict comparison
      // called that a slice and refused to snap. Sub-pixel slivers are not
      // visible, so tolerate a couple of pixels either way.
      const EPS = 2;
      const clean = (at) => {
        const top = topAbs - at;
        const bottom = bottomAbs - at;
        return top >= nav.bottom - EPS || (bottom <= nav.bottom + EPS && top >= nav.top - EPS);
      };
      if (!clean(target) && clean(max)) target = max;
    }
    if (Math.abs(target - sy) < 1) return;
    window.scrollTo({ top: target, behavior: reduceMotion ? "auto" : "smooth" });
  }, [compact, pinned, reduceMotion]);
  const onHover = useCallback((i) => setHovered(i), []);
  const onLayout = useCallback((g) => setGeo(g), []);

  const stage = (
    <ParticleImage
      src="/people/team.webp"
      bands={BANDS}
      boardTop={BOARD_TOP}
      target={36000}
      disperse={16}
      focus={active}
      zoomOnFocus={compact}
      onHover={compact ? undefined : onHover}
      onSelect={onSelect}
      onLayout={onLayout}
    />
  );

  /* ---- compact: one scrolling column, tap-driven ------------------- */
  if (compact) {
    return (
      <div className="ev-home ev-people pv-flow">
        <SiteNav className={navClassName} />

        <header>
          <h1 className="pv-title" ref={headingRef}>Founders</h1>
          <p className="pv-hint pv-head-hint">
            <b>Select a name</b>
          </p>
        </header>

        <div className="pv-stage" aria-hidden="true">
          {stage}
        </div>

        <nav aria-label="Team members">
          <Roster people={PEOPLE} active={active} pinned={pinned} onSelect={onSelect} onHover={onHover} />
        </nav>

        <div className="pv-bio" id="pv-bio" aria-live="polite" ref={bioRef}>
          {person ? (
            <div data-person-bio>
              <h2 className="pv-bio-name" data-bio-name>
                {person.name}
              </h2>
              <ul className="pv-bio-lines">
                {person.lines.map((l) => (
                  <li key={l} data-bio-line>
                    {l}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  /* ---- desktop: fixed stage, left rail, blurb in the empty space --- */
  let blurbStyle = null;
  let fit = null;
  let wrapText = false;
  if (person && geo?.anchors?.[active]) {
    const a = geo.anchors[active];
    const s = geo.stage;
    const rightTwo = active >= 2; // left two → blurb on the right; right two → on the left
    // Center the blurb within the empty space around the figure — vertically
    // from the figure's top down to where the board begins, and horizontally
    // from the figure's edge out to the far edge of the stage (never under the
    // person list, which owns everything left of the stage).
    const boxTop = Math.max(96, a.top);
    const boxHeight = Math.max(120, a.bottom - boxTop);
    const regionLeft = rightTwo ? s.left : a.right;
    const regionRight = rightTwo ? a.left : s.right;
    const boxWidth = Math.max(0, regionRight - regionLeft);
    const pad = 32;
    const availWidth = Math.max(0, boxWidth - pad * 2);
    const availHeight = Math.max(0, boxHeight - pad * 2);
    // Below this width no font size fits the longer bio lines on a single row,
    // so wrap normally instead of shrinking to unreadable or truncating.
    wrapText = boxWidth < 460;
    fit = wrapText
      ? fitBlurbSizeWrapped(person, availWidth, availHeight)
      : fitBlurbSize(person, availWidth, availHeight);
    blurbStyle = {
      position: "fixed",
      top: boxTop,
      height: boxHeight,
      left: regionLeft,
      width: boxWidth,
      zIndex: 5,
      pointerEvents: "none",
      fontFamily: `var(--ev-fs, ${BLURB_FONT})`,
      color: "#fff",
      textAlign: "center",
    };
  }

  return (
    <div className="ev-home ev-people pv-desk" style={{ background: "#050506" }}>
      <SiteNav className={navClassName} />

      <div className="pv-rail">
        <div className="pv-rail-head">
          <h1 className="pv-title">Founders</h1>
        {/* Hint sits ABOVE the list: below it, it was read after the control it
            describes, which is too late to act as an affordance. */}
          <p className="pv-hint">
            <b>Select a name</b>
          </p>
        </div>
        <nav aria-label="Team members">
          <Roster people={PEOPLE} active={active} pinned={pinned} onSelect={onSelect} onHover={onHover} />
        </nav>
      </div>

      <main className="pv-stage" aria-label="6thSense team — select a person to reveal them">
        {stage}
      </main>

      {/* The live region must exist at page load, otherwise most screen readers
          never register it and announce nothing when it later appears. Only its
          CONTENT is conditional. */}
      <aside id="pv-bio" aria-live="polite" style={blurbStyle || BLURB_SHELL_IDLE}>
        {person && fit && (
          <div data-person-bio style={BLURB_INNER}>
            <div
              className="pv-blurb-name"
              data-bio-name
              style={{
                fontSize: fit.nameSize,
                marginBottom: fit.gap,
                whiteSpace: wrapText ? "normal" : "nowrap",
                overflow: wrapText ? "visible" : "hidden",
                textOverflow: wrapText ? "clip" : "ellipsis",
              }}
            >
              {person.name}
            </div>
            {person.lines.map((l) => (
              <div
                key={l}
                className="pv-blurb-line"
                data-bio-line
                style={{
                  fontSize: fit.lineSize,
                  lineHeight: LINE_LINE_HEIGHT,
                  whiteSpace: wrapText ? "normal" : "nowrap",
                  overflow: wrapText ? "visible" : "hidden",
                  textOverflow: wrapText ? "clip" : "ellipsis",
                }}
              >
                {l}
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}
