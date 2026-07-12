import { useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";

import SiteNav from "../SiteNav.jsx";
import { useRevealNav } from "../useRevealNav.js";
import ParticleImage from "../lib/ParticleImage.jsx";
import "../evora-home.css";

/**
 * 6thSense /people — navbar + a particle team photo on black. The YC board stays
 * as fixed particles; hover a person and their dots resolve into their real
 * (translucent, feathered) photo while the others fade, with a pure-text blurb
 * beside them.
 *
 * PEOPLE is left → right as they stand. Position 0 = Alex (confirmed); the other
 * three (1,2,3) are a best guess — reorder if wrong.
 */
const BANDS = [0, 0.28, 0.44, 0.63, 1]; // 4 people; index 4 = board

const BLURB_FONT = "'General Sans', system-ui, sans-serif";
const LINE_SCALE = 0.6; // info-line size relative to the name size
const GAP_SCALE = 1.0; // name→info gap relative to the name size
const NAME_LINE_HEIGHT = 1.2;
const LINE_LINE_HEIGHT = 1.75;
const MIN_NAME_SIZE = 26;
const MAX_NAME_SIZE = 92;
const MIN_NAME_SIZE_WRAPPED = 16; // phones: shrink further before we'd rather wrap than truncate

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
// line within the available box — so hovering never produces an awkward
// mid-word wrap.
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

// Narrow phones: the box usually isn't wide enough to fit every bio line on
// one row, so simulate the actual word-wrap at each candidate size and shrink
// until the wrapped block fits the available height (rather than assuming
// one row per line, which underestimates height once lines wrap to two+).
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

export default function PeoplePage() {
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });
  const [focus, setFocus] = useState(null); // { idx, anchor }

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

  const person = focus != null ? PEOPLE[focus.idx] : null;
  let blurbStyle = null;
  let fit = null;
  let wrapText = false;
  if (focus && person) {
    const vw = window.innerWidth;
    const a = focus.anchor;
    const rightTwo = focus.idx >= 2; // left two → blurb on the right; right two → on the left
    // Center the blurb within the empty space around the figure — vertically
    // from the figure's top down to where the board begins, and horizontally
    // from the figure's edge out to the far edge of the viewport — rather
    // than centering in the whole container.
    const boxTop = Math.max(96, a.top);
    const boxHeight = Math.max(120, a.bottom - boxTop);
    const regionLeft = rightTwo ? 0 : a.right;
    const regionRight = rightTwo ? a.left : vw;
    const boxWidth = Math.max(0, regionRight - regionLeft);
    const pad = 32;
    const availWidth = Math.max(0, boxWidth - pad * 2);
    const availHeight = Math.max(0, boxHeight - pad * 2);
    // Below this width there's no font size that fits the longer bio lines on
    // a single line (narrow phones) — wrap normally instead of shrinking to
    // an unreadable size or truncating with an ellipsis.
    wrapText = boxWidth < 460;
    fit = wrapText
      ? fitBlurbSizeWrapped(person, availWidth, availHeight)
      : fitBlurbSize(person, availWidth, availHeight);
    blurbStyle = {
      position: "fixed", top: boxTop, height: boxHeight,
      left: regionLeft, width: boxWidth,
      zIndex: 5, pointerEvents: "none",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: `var(--ev-fs, ${BLURB_FONT})`, color: "#fff", textAlign: "center",
    };
  }

  return (
    <div className="ev-home ev-people" style={{ background: "#050506", height: "100vh", overflow: "hidden" }}>
      <SiteNav className={navClassName} />

      <main aria-label="6thSense team — hover a person to reveal them" style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <ParticleImage
          src="/people/team.webp"
          bands={BANDS}
          boardTop={0.6}
          target={36000}
          disperse={16}
          onFocus={(idx, anchor) => setFocus(idx != null ? { idx, anchor } : null)}
        />
      </main>

      {person && fit && (
        <aside style={blurbStyle} aria-live="polite">
          <div
            style={{
              fontSize: fit.nameSize, fontWeight: 600, letterSpacing: "-0.01em", marginBottom: fit.gap,
              maxWidth: "100%",
              whiteSpace: wrapText ? "normal" : "nowrap",
              overflow: wrapText ? "visible" : "hidden",
              textOverflow: wrapText ? "clip" : "ellipsis",
            }}
          >
            {person.name}
          </div>
          {person.lines.map((l, i) => (
            <div
              key={i}
              style={{
                fontSize: fit.lineSize, lineHeight: LINE_LINE_HEIGHT, color: "rgba(255,255,255,0.85)",
                maxWidth: "100%",
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
