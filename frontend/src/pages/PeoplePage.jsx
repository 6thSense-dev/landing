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
 * PEOPLE is left → right as they stand. Position 0 = Alex (confirmed); the other
 * three (1,2,3) are a best guess — reorder if wrong.
 */
const BANDS = [0, 0.28, 0.44, 0.63, 1]; // 4 people; index 4 = board
const BOARD_TOP = 0.6;
const COMPACT_QUERY = "(max-width: 1023px)";

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
      "Delivered chickens faster with robots at Chick-fil-a.",
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
    <ul className="pv-roster" onMouseLeave={() => onHover(null)}>
      {people.map((p, i) => (
        <li key={p.name}>
          <button
            type="button"
            className={`pv-item${active === i ? " is-active" : ""}`}
            data-person-btn={i}
            aria-pressed={pinned === i}
            aria-controls="pv-bio"
            onClick={() => onSelect(pinned === i ? null : i)}
            onMouseEnter={() => onHover(i)}
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
  // of the screen would land off-frame. Bring it into view on selection.
  useEffect(() => {
    if (!compact || pinned == null || !bioRef.current) return;
    bioRef.current.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "end",
    });
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
          <h1 className="pv-title">The team</h1>
          <p className="pv-hint pv-head-hint">
            <b>Tap a name</b> to reveal them
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
          ) : (
            <p className="pv-bio-empty">Nobody selected yet. Tap a name above and their photo resolves out of the dots.</p>
          )}
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
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: `var(--ev-fs, ${BLURB_FONT})`,
      color: "#fff",
      textAlign: "center",
    };
  }

  return (
    <div className="ev-home ev-people pv-desk" style={{ background: "#050506" }}>
      <SiteNav className={navClassName} />

      <div className="pv-rail">
        <h1 className="pv-title">The team</h1>
        <nav aria-label="Team members">
          <Roster people={PEOPLE} active={active} pinned={pinned} onSelect={onSelect} onHover={onHover} />
        </nav>
        <p className="pv-hint">
          <b>Hover or click a name</b>
          <br />
          to reveal them
        </p>
      </div>

      <main className="pv-stage" aria-label="6thSense team — select a person to reveal them">
        {stage}
      </main>

      {person && fit && (
        <aside style={blurbStyle} id="pv-bio" aria-live="polite" data-person-bio>
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
        </aside>
      )}
    </div>
  );
}
