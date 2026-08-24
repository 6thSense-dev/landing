/**
 * CatalogGrid — the 1 / 2 / 3-up card grid.
 *
 * Renders nothing but cards: the empty state, the heading and the section chrome belong to the
 * page. Budgeted for 1000 cards, so:
 *  - `onOpen` is stabilised here, which lets ClipCard's memo comparator reduce to an id check;
 *  - the reveal is CSS, not framer-motion. A motion component per cell is a subscription, a
 *    props object and a style write per card; a keyframe on the cell is none of those, and it
 *    lets the "first row only" cap be expressed against the SAME breakpoints that decide how
 *    many columns there are (see parts.grid.css). Only three inline style objects exist in the
 *    whole module and they are frozen at load;
 *  - the per-card `content-visibility` in parts.grid.css keeps offscreen cards out of layout.
 *
 * The column count itself is catalog.css's call (`--cat-grid-cols`, 1 / 2 / 3 at 720 px and
 * 1000 px). Nothing here hard-codes it.
 */
import React, { useCallback, useEffect, useRef } from "react";
import ClipCard from "./ClipCard.jsx";

/**
 * Per-cell reveal delay, as a custom property. Capped at three because three is the widest
 * the grid ever gets; parts.grid.css then narrows the cap to the ACTUAL first row at each
 * breakpoint with :nth-child, and drops it entirely under prefers-reduced-motion. Frozen at
 * module scope so no card is handed a fresh style object.
 */
const CELL_VARS = [
  Object.freeze({ "--cat-cell-i": 0 }),
  Object.freeze({ "--cat-cell-i": 1 }),
  Object.freeze({ "--cat-cell-i": 2 }),
];

const EMPTY = [];

export default function CatalogGrid({ clips, onOpen, collection, countryLabels }) {
  const list = Array.isArray(clips) ? clips : EMPTY;

  /* Latest-ref indirection: the page may rebuild `onOpen` on every render, and without this
     every memoised card would re-render with it. Opening happens from a click, long after
     effects have flushed, so the ref is never stale at call time. */
  const onOpenRef = useRef(onOpen);
  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);
  const stableOpen = useCallback((id) => {
    const fn = onOpenRef.current;
    if (fn) fn(id);
  }, []);

  return (
    <div className="cat-grid" role="list">
      {list.map((clip, i) => (
        <div
          className="cat-grid__cell"
          role="listitem"
          key={clip.id}
          style={i < CELL_VARS.length ? CELL_VARS[i] : undefined}
        >
          <ClipCard
            clip={clip}
            onOpen={stableOpen}
            collection={collection}
            countryLabels={countryLabels}
          />
        </div>
      ))}
    </div>
  );
}
