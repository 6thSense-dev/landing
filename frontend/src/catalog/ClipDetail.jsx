/**
 * ClipDetail — the buyer-facing clip modal (6s-catalog/1.0).
 * ---------------------------------------------------------------------------
 * <ClipDetail clipId={string|null} onClose={() => {}} onNavigate={(dir) => {}} />
 *
 *   clipId      null  -> renders nothing at all.
 *   onClose     called on Escape, on the close button, on backdrop click.
 *   onNavigate  called with -1 / +1 when the user presses Left/Right arrow while
 *               focus is NOT inside the tab list, a text field, or a region that
 *               has claimed the arrow keys for itself (`data-arrowkeys="own"`).
 *
 * Layout, matching the reference screenshots:
 *
 *   +-----------------------------------------------------------+
 *   |  dark media panel   LEFT CAMERA ............ RIGHT CAMERA  |  <- always present
 *   |  (the Video tab lives *here*, controls and all;            |
 *   |   every other tab collapses it to a poster strip)          |
 *   +-----------------------------------------------------------+
 *   |  CATEGORY / COUNTRY / M:SS     [Video][IMU][Tactile][...]  |  <- paper bar
 *   |  Title ArrowUpRight                                        |
 *   +-----------------------------------------------------------+
 *   |  active tab panel (paper, scrolls)                         |
 *   +-----------------------------------------------------------+
 *
 * Cross-tab messaging (no prop drilling — every tab receives `{ clip }`, and the
 * Video tab one callback on top of it: the LEFT/RIGHT CAMERA labels above are
 * drawn by THIS component and are wrong over the tactile-overlay render, so it
 * reports which view is playing):
 *
 *   window event "6s-catalog:seek"  detail: { clipId, t_s }
 *     dispatched by  SegcapTab / TactileTab
 *     heard by       ClipDetail  -> switches to the Video tab
 *                    VideoTab    -> seeks (and, if it was not mounted at dispatch
 *                                  time, drains the `window.__6sCatalogSeek`
 *                                  mailbox that the dispatcher also writes)
 *
 * Tokens: the overlay root carries the `cat-root` class so the catalog's own
 * token block (defined in catalog.css) applies inside the portal, which lives
 * outside the catalog subtree in the DOM. Detail-only tokens are in
 * parts.detail.css.
 */

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, useReducedMotion } from "framer-motion";
import {
  AlignLeft,
  ArrowUpRight,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Film,
  Grid2x2,
  Hand,
  RotateCw,
  Ruler,
  X,
} from "lucide-react";

import { useClip, assetUrl, notifyAssetExpired, facetLabel } from "./useCatalog.js";
/* Namespace import so an optional export (clearCatalogCache, used by Retry)
   can be probed without turning a missing symbol into a build failure. */
import * as CatalogApi from "./useCatalog.js";
import { formatDuration, dash } from "./format.js";

import VideoTab from "./tabs/VideoTab.jsx";
import ImuTab from "./tabs/ImuTab.jsx";
import TactileTab from "./tabs/TactileTab.jsx";
import SegcapTab from "./tabs/SegcapTab.jsx";
import CalibrationTab from "./tabs/CalibrationTab.jsx";
import MetadataTab from "./tabs/MetadataTab.jsx";

import "./parts.detail.css";

export const SEEK_EVENT = "6s-catalog:seek";

const TABS = [
  { id: "video", label: "Video", Icon: Film },
  { id: "imu", label: "IMU", Icon: BarChart3 },
  { id: "tactile", label: "Tactile", Icon: Hand },
  { id: "segcap", label: "Segcap", Icon: Grid2x2 },
  /* H3 + H7. Both are hard rejection criteria on a robotics data buy and both
     were fully populated in every record and rendered nowhere; the only way to
     read them was the "Copy JSON" button. They sit before Metadata because a
     perception team screens on them before anything else in this modal. */
  { id: "calibration", label: "Calib & sync", Icon: Ruler },
  { id: "metadata", label: "Metadata", Icon: AlignLeft },
];

const FOCUSABLE = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "video[controls]",
  "audio[controls]",
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(",");

/* ------------------------------------------------------------------ */
/* useClip() shape normaliser.                                         */
/* The hook may return the record itself, or a { clip|data, loading,   */
/* error, retry } envelope. Both are accepted so the modal does not     */
/* break if the data layer settles on either convention.                */
/* ------------------------------------------------------------------ */
function normaliseClipState(result) {
  if (result == null) return { clip: null, loading: true, error: null, retry: null };
  if (typeof result !== "object") return { clip: null, loading: false, error: null, retry: null };
  const looksLikeRecord =
    result.schema === "6s-clip/1.0" || (typeof result.id === "string" && "title" in result);
  if (looksLikeRecord) return { clip: result, loading: false, error: null, retry: null };
  const clip = result.clip ?? result.data ?? result.record ?? null;
  const loading =
    typeof result.status === "string"
      ? result.status === "loading" || result.status === "idle"
      : (result.loading ?? result.isLoading ?? result.pending ?? (!clip && !result.error));
  return {
    clip,
    loading: Boolean(loading),
    error: result.error ?? result.err ?? null,
    retry: result.retry ?? result.refetch ?? result.reload ?? null,
  };
}

/* ------------------------------------------------------------------ */
/* URL hash: `#tab=imu`. Other `&`-joined keys in the hash are          */
/* preserved so we never clobber a clip id the grid may have put there. */
/* ------------------------------------------------------------------ */
function readHashTab() {
  if (typeof window === "undefined") return null;
  const raw = window.location.hash.replace(/^#/, "");
  for (const part of raw.split("&")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq) === "tab") return decodeURIComponent(part.slice(eq + 1));
  }
  return null;
}

function writeHashTab(tabId) {
  if (typeof window === "undefined") return;
  const raw = window.location.hash.replace(/^#/, "");
  const parts = raw ? raw.split("&").filter(Boolean) : [];
  let found = false;
  const next = parts.map((part) => {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq) === "tab") {
      found = true;
      return `tab=${tabId}`;
    }
    return part;
  });
  if (!found) next.push(`tab=${tabId}`);
  const url = `${window.location.pathname}${window.location.search}#${next.join("&")}`;
  try {
    window.history.replaceState(window.history.state, "", url);
  } catch {
    /* replaceState can throw in sandboxed frames; the tab still works. */
  }
}

/* Which tabs have anything to show for this record. */
function enabledTabs(clip) {
  if (!clip) {
    return {
      video: true, imu: false, tactile: false, segcap: false,
      calibration: false, metadata: true,
    };
  }
  const video = Boolean(clip.media?.video) || Boolean(clip.poster);
  return {
    video,
    imu: clip.imu_preview != null,
    tactile: clip.tactile_preview != null || (clip.hands?.length ?? 0) > 0,
    segcap: (clip.segments?.length ?? 0) > 0,
    calibration: clip.calibration != null || clip.sync != null,
    metadata: true,
  };
}

/* The single asset the title's ArrowUpRight opens in a new tab. */
function primaryAsset(clip) {
  const v = clip?.media?.video;
  const rel = v?.stereo_sbs || v?.mono || v?.left || clip?.poster || null;
  if (!rel) return null;
  try {
    return assetUrl(rel);
  } catch {
    return null;
  }
}

function cameraLabels(clip) {
  if (clip?.capture !== "stereo_egocentric") return ["CAMERA", null];
  const video = clip?.media?.video;
  /* `layout` describes how the two eyes sit inside a COMPOSITE frame, so it
     only tells us which corner is which when the composite is what plays.
     Separately encoded eyes are always rendered left-then-right. */
  if (video?.stereo_sbs && video?.layout === "side_by_side_rl") {
    return ["RIGHT CAMERA", "LEFT CAMERA"];
  }
  return ["LEFT CAMERA", "RIGHT CAMERA"];
}

/* =================================================================== */
/* Public wrapper. Its hooks are unconditional and its early return is   */
/* the last statement, so toggling clipId between null and a string      */
/* never reorders hooks. Everything that must survive a Retry remount    */
/* (focus restore, the scroll lock) lives here rather than in the inner  */
/* component, which is keyed on the retry counter.                       */
/* =================================================================== */
export default function ClipDetail({ clipId, onClose, onNavigate }) {
  /* Hooks run unconditionally so toggling clipId never reorders them; the
     early return below is what makes "clipId === null renders nothing" true. */
  const [attempt, setAttempt] = useState(0);
  const openerRef = useRef(null);
  const open = Boolean(clipId);

  /* Remember who opened us and give focus back on close. CatalogPage does the
     same thing from its side; both target the same card, so the modal stays
     correct when it is dropped into a host that does not. */
  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const active = document.activeElement;
    openerRef.current =
      active instanceof HTMLElement && active !== document.body ? active : null;
    return () => {
      const opener = openerRef.current;
      openerRef.current = null;
      if (!opener || !document.contains(opener)) return;
      requestAnimationFrame(() => {
        try {
          opener.focus({ preventScroll: true });
        } catch {
          /* the card was re-rendered away between frames */
        }
      });
    };
  }, [open]);

  /* Background scroll lock. CatalogPage already locks <html> with a gutter
     compensation; doing it again would double the gutter and shift the page,
     so we defer to the host whenever it has already claimed the lock. */
  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const root = document.documentElement;
    if (root.classList.contains("cat-scroll-locked")) return undefined;
    const { body } = document;
    const prevOverflow = body.style.overflow;
    const prevPadding = body.style.paddingRight;
    const gutter = window.innerWidth - root.clientWidth;
    body.style.overflow = "hidden";
    if (gutter > 0) body.style.paddingRight = `${gutter}px`;
    return () => {
      body.style.overflow = prevOverflow;
      body.style.paddingRight = prevPadding;
    };
  }, [open]);

  const retry = useCallback(() => {
    try {
      CatalogApi.clearCatalogCache?.();
    } catch {
      /* the data layer does not expose a cache; the remount alone may suffice */
    }
    setAttempt((a) => a + 1);
  }, []);

  if (!open) return null;
  return (
    <ClipDetailInner
      /* Keyed on the retry counter only: remount to re-run the fetch, but do
         NOT remount when clipId changes, so arrowing between clips keeps the
         selected tab. */
      key={attempt}
      clipId={clipId}
      onClose={onClose}
      onNavigate={onNavigate}
      onRetry={retry}
    />
  );
}

function ClipDetailInner({ clipId, onClose, onNavigate, onRetry }) {
  const reduced = useReducedMotion();
  const state = normaliseClipState(useClip(clipId));
  const { clip, loading, error, retry } = state;

  const overlayRef = useRef(null);
  const panelRef = useRef(null);
  const titleId = useId();
  const panelId = useId();

  const [tab, setTab] = useState(() => {
    const fromHash = readHashTab();
    return TABS.some((t) => t.id === fromHash) ? fromHash : "video";
  });
  /* Which view the Video tab is playing, as it reports it. Only the eye labels
     read it, and only while that tab is the one on screen. */
  const [mediaView, setMediaView] = useState(null);

  const enabled = useMemo(() => enabledTabs(clip), [clip]);

  /* Move focus into the panel once it exists. */
  useEffect(() => {
    const node = panelRef.current;
    if (!node) return;
    const first = node.querySelector("[data-autofocus]") || node;
    requestAnimationFrame(() => {
      try {
        first.focus({ preventScroll: true });
      } catch {
        /* noop */
      }
    });
  }, []);

  /* A tab that is not available for this record falls back to a live one. */
  useEffect(() => {
    if (!clip) return;
    if (enabled[tab]) return;
    const next = TABS.find((t) => enabled[t.id]);
    if (next) setTab(next.id);
  }, [clip, enabled, tab]);

  /* Re-assert on clipId too: CatalogPage navigates with react-router, which
     rebuilds the URL from its own location and would otherwise drop the hash
     when the user arrows to the next clip. */
  useEffect(() => {
    writeHashTab(tab);
  }, [tab, clipId]);

  /* SegcapTab / TactileTab ask for a video seek -> come to the front. */
  useEffect(() => {
    function onSeek(event) {
      const detail = event?.detail;
      if (!detail) return;
      if (detail.clipId && detail.clipId !== clipId) return;
      setTab("video");
    }
    window.addEventListener(SEEK_EVENT, onSeek);
    return () => window.removeEventListener(SEEK_EVENT, onSeek);
  }, [clipId]);

  const close = useCallback(() => {
    onClose?.();
  }, [onClose]);

  const onKeyDown = useCallback(
    (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        close();
        return;
      }

      if (event.key === "Tab") {
        const root = panelRef.current;
        if (!root) return;
        /*
         * TABBABLE, not merely focusable.
         *
         * FOCUSABLE contains `button:not([disabled])`, and the tab strip marks its
         * unselected tabs with tabIndex={-1} + aria-disabled (a roving tabindex), not
         * with `disabled`. All six therefore matched, so `items[items.length - 1]` was
         * the Metadata BUTTON — an element the Tab key can never reach. On the default
         * Video tab the body is not rendered at all (`clip && !isVideoTab`), which makes
         * the tab strip the end of the DOM: pressing Tab on the selected Video tab failed
         * the `active === last` test, nothing was prevented, and focus escaped the
         * aria-modal dialog into the browser chrome and the grid behind it. Same on the
         * loading and error skeletons. Verified in Chromium: items.length === 14, last =
         * "Metadata" (tabindex=-1), while the last genuinely tabbable node was the "Video"
         * tab button.
         *
         * `el.tabIndex >= 0` is the whole fix: a roving-tabindex -1 node is reachable by
         * arrow keys and by script, and by definition not by Tab.
         */
        const items = Array.from(root.querySelectorAll(FOCUSABLE)).filter(
          (el) =>
            el.tabIndex >= 0 && (el.offsetParent !== null || el === document.activeElement)
        );
        if (items.length === 0) {
          event.preventDefault();
          root.focus();
          return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (event.shiftKey && (active === first || active === root)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }

      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;

      /* Arrows only move between clips when nothing nearer wants them. */
      const active = document.activeElement;
      if (active instanceof HTMLElement) {
        if (active.closest('[role="tablist"]')) return;
        if (active.closest('[data-arrowkeys="own"]')) return;
        if (active.isContentEditable) return;
        const tag = active.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      }
      if (!onNavigate) return;
      event.preventDefault();
      onNavigate(event.key === "ArrowLeft" ? -1 : 1);
    },
    [close, onNavigate]
  );

  const [labelA, labelB] = cameraLabels(clip);
  const isVideoTab = tab === "video";
  /* The labels name the two halves of a stereo frame. The tactile overlay is one
     composed picture, so over it they would be labelling nothing. */
  const showCamLabels = !(isVideoTab && mediaView === "overlay");
  const assetHref = primaryAsset(clip);
  const posterHref = clip?.poster ? assetUrl(clip.poster) : null;

  /* Kept as PARTS rather than one joined string: the duration is a
     measurement and wears tabular figures, the other two are prose. Joining
     them first would have made that impossible without a regex. */
  const crumbs = clip
    ? [
        { text: dash(clip.category ? humanise(clip.category) : null), num: false },
        /* The NAME, from facets.country[].label -- the card and the filter bar
           both show "China", and the modal must not be the one surface that
           prints the join key at a buyer. */
        { text: dash(clip.country ? facetLabel("country", clip.country) : null), num: false },
        {
          text: dash(clip.duration_s != null ? formatDuration(clip.duration_s) : null),
          num: true,
        },
      ]
    : null;

  const overlay = (
    <div
      className="cat-root cat-d-overlay"
      ref={overlayRef}
      onKeyDown={onKeyDown}
      onMouseDown={(e) => {
        if (e.target === overlayRef.current) close();
      }}
    >
      <motion.div
        className="cat-d-panel"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        initial={reduced ? false : { opacity: 0, scale: 0.975, y: 8 }}
        animate={reduced ? {} : { opacity: 1, scale: 1, y: 0 }}
        transition={reduced ? { duration: 0 } : { duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      >
        <button
          type="button"
          className="cat-d-close"
          onClick={close}
          data-autofocus
          aria-label="Close clip detail"
        >
          <X size={16} aria-hidden="true" />
        </button>

        {onNavigate ? (
          <div className="cat-d-nav" aria-hidden={false}>
            <button
              type="button"
              className="cat-d-navbtn"
              onClick={() => onNavigate(-1)}
              aria-label="Previous clip"
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="cat-d-navbtn"
              onClick={() => onNavigate(1)}
              aria-label="Next clip"
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {/* ---------------- dark media region ---------------- */}
        <div className={`cat-d-media${isVideoTab ? "" : " cat-d-media--compact"}`}>
          {showCamLabels ? (
            <span className="cat-d-camlabel cat-d-camlabel--l" aria-hidden="true">
              {labelA}
            </span>
          ) : null}
          {showCamLabels && labelB ? (
            <span className="cat-d-camlabel cat-d-camlabel--r" aria-hidden="true">
              {labelB}
            </span>
          ) : null}

          {loading || error || !clip ? (
            <MediaPlaceholder loading={loading} error={error} />
          ) : isVideoTab ? (
            <div
              className="cat-d-tabpanel cat-d-tabpanel--media"
              role="tabpanel"
              id={`${panelId}-video`}
              aria-labelledby={`${panelId}-tab-video`}
              tabIndex={-1}
            >
              <VideoTab clip={clip} onViewChange={setMediaView} />
            </div>
          ) : (
            <button
              type="button"
              className="cat-d-posterstrip"
              onClick={() => setTab("video")}
              aria-label={`Back to the video for ${clip.title}`}
            >
              {posterHref ? (
                <img
                  src={posterHref}
                  onError={() => notifyAssetExpired(posterHref)}
                  alt=""
                  aria-hidden="true"
                />
              ) : (
                <span className="cat-d-posterstrip__empty" aria-hidden="true" />
              )}
              <span className="cat-d-posterstrip__cta">Back to video</span>
            </button>
          )}
        </div>

        {/* ---------------- paper bar: title + tabs ---------------- */}
        <div className="cat-d-bar">
          <div className="cat-d-heading">
            {/* Eyebrow first: category, country and length orient the buyer
                before the title hands them a name. */}
            <p className="cat-label cat-d-crumb">
              {crumbs
                ? crumbs.map((c, i) => (
                    <Fragment key={i}>
                      {i > 0 ? (
                        <span className="cat-d-crumb__sep" aria-hidden="true">
                          /
                        </span>
                      ) : null}
                      <span className={c.num ? "cat-num" : undefined}>{c.text}</span>
                    </Fragment>
                  ))
                : "—"}
            </p>
            <h2 className="cat-d-title" id={titleId}>
              <span>{clip ? clip.title : "Loading clip"}</span>
              {assetHref ? (
                <a
                  className="cat-d-titlelink"
                  href={assetHref}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label={`Open the source asset for ${clip.title} in a new tab`}
                >
                  <ArrowUpRight size={15} aria-hidden="true" />
                </a>
              ) : null}
            </h2>
          </div>

          <TabList
            tab={tab}
            setTab={setTab}
            enabled={enabled}
            panelId={panelId}
            disabled={!clip}
          />
        </div>

        {/* ---------------- paper body: everything but Video ---------------- */}
        {loading && !clip ? (
          <div className="cat-d-body">
            <DetailSkeleton />
          </div>
        ) : error && !clip ? (
          <div className="cat-d-body">
            <ErrorState
              error={error}
              onRetry={() => {
                retry?.();
                onRetry?.();
              }}
              onClose={close}
            />
          </div>
        ) : clip && !isVideoTab ? (
          <div className="cat-d-body">
            <div
              className="cat-d-tabpanel"
              role="tabpanel"
              id={`${panelId}-${tab}`}
              aria-labelledby={`${panelId}-tab-${tab}`}
              tabIndex={-1}
            >
              {tab === "imu" ? <ImuTab clip={clip} /> : null}
              {tab === "tactile" ? <TactileTab clip={clip} /> : null}
              {tab === "segcap" ? <SegcapTab clip={clip} /> : null}
              {tab === "calibration" ? <CalibrationTab clip={clip} /> : null}
              {tab === "metadata" ? <MetadataTab clip={clip} /> : null}
            </div>
          </div>
        ) : null}
      </motion.div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(overlay, document.body);
}

/* =================================================================== */
/* Tab list — roving tabindex, Left/Right/Home/End, disabled tabs skipped */
/* =================================================================== */
function TabList({ tab, setTab, enabled, panelId, disabled }) {
  const ref = useRef(null);
  /* Which EDGE is faded, i.e. which side still has tabs past the fold.
     parts.detail.css turns this into a mask, so an overflowing strip announces
     itself instead of ending in a hard cut. */
  const [edge, setEdge] = useState("none");

  const syncEdges = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    if (max <= 2) {
      setEdge("none");
      return;
    }
    const atStart = el.scrollLeft <= 2;
    const atEnd = el.scrollLeft >= max - 2;
    setEdge(atStart ? "end" : atEnd ? "start" : "both");
  }, []);

  /* Re-measure when the strip or any tab changes size: the labels are the
     widest thing in it and they only settle once the webfont has swapped in. */
  useEffect(() => {
    syncEdges();
    const el = ref.current;
    if (!el) return undefined;
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", syncEdges);
      return () => window.removeEventListener("resize", syncEdges);
    }
    const ro = new ResizeObserver(syncEdges);
    ro.observe(el);
    for (const child of Array.from(el.children)) ro.observe(child);
    return () => ro.disconnect();
  }, [syncEdges]);

  /* Keep the selected tab on screen. The roving tabindex moves focus to it, and
     a focused control the user cannot see is worse than no scroller at all.
     scrollLeft, not scrollIntoView(): the latter walks up the ancestor chain
     and would scroll the modal body and the page behind it too. */
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const raf = requestAnimationFrame(() => {
      const btn = el.querySelector('[aria-selected="true"]');
      const max = el.scrollWidth - el.clientWidth;
      if (btn && max > 2) {
        const want = btn.offsetLeft - (el.clientWidth - btn.offsetWidth) / 2;
        el.scrollLeft = Math.max(0, Math.min(want, max));
      }
      syncEdges();
    });
    return () => cancelAnimationFrame(raf);
  }, [tab, syncEdges]);

  const move = (dir) => {
    const live = TABS.filter((t) => enabled[t.id]);
    if (live.length === 0) return;
    const at = live.findIndex((t) => t.id === tab);
    const next = live[(at + dir + live.length) % live.length];
    setTab(next.id);
    requestAnimationFrame(() => {
      ref.current?.querySelector(`#${CSS.escape(`${panelId}-tab-${next.id}`)}`)?.focus();
    });
  };

  const jump = (which) => {
    const live = TABS.filter((t) => enabled[t.id]);
    if (live.length === 0) return;
    const next = which === "home" ? live[0] : live[live.length - 1];
    setTab(next.id);
    requestAnimationFrame(() => {
      ref.current?.querySelector(`#${CSS.escape(`${panelId}-tab-${next.id}`)}`)?.focus();
    });
  };

  return (
    <div
      className="cat-d-tabs"
      data-edge={edge}
      onScroll={syncEdges}
      role="tablist"
      aria-label="Clip detail sections"
      ref={ref}
    >
      {TABS.map(({ id, label, Icon }) => {
        const on = tab === id;
        const live = Boolean(enabled[id]) && !disabled;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            id={`${panelId}-tab-${id}`}
            aria-controls={`${panelId}-${id}`}
            aria-selected={on}
            aria-disabled={live ? undefined : true}
            tabIndex={on ? 0 : -1}
            className={`cat-d-tab${on ? " is-on" : ""}${live ? "" : " is-off"}`}
            onClick={() => live && setTab(id)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") {
                e.preventDefault();
                move(1);
              } else if (e.key === "ArrowLeft") {
                e.preventDefault();
                move(-1);
              } else if (e.key === "Home") {
                e.preventDefault();
                jump("home");
              } else if (e.key === "End") {
                e.preventDefault();
                jump("end");
              }
            }}
            title={live ? undefined : `${label} — not available for this clip`}
          >
            <Icon size={14} aria-hidden="true" />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* =================================================================== */
/* States                                                               */
/* =================================================================== */
function MediaPlaceholder({ loading, error }) {
  return (
    <div className="cat-d-mediaskel" role="status" aria-live="polite">
      <span className="cat-sr">{error ? "Clip failed to load" : "Loading clip"}</span>
      {loading ? <span className="cat-d-shimmer" aria-hidden="true" /> : null}
    </div>
  );
}

/* Not a generic stack of bars: the same three columns, row height and hairline
   the metadata grid resolves to, so the panel does not resize under the
   pointer when the record lands (CLS 0). */
const SKELETON_CELLS = [0, 1, 2, 3, 4, 5, 6, 7, 8];
const SKELETON_LINES = ["94%", "88%", "62%"];

function DetailSkeleton() {
  return (
    <div className="cat-d-skel" aria-hidden="true">
      <div className="cat-d-skel__grid">
        {SKELETON_CELLS.map((i) => (
          <div className="cat-d-skel__cell" key={i}>
            <span className="cat-d-skel__lab cat-d-shimmer" />
            <span className="cat-d-skel__val cat-d-shimmer" />
          </div>
        ))}
      </div>
      <div className="cat-d-skel__para">
        {SKELETON_LINES.map((w) => (
          <span className="cat-d-skel__line cat-d-shimmer" key={w} style={{ width: w }} />
        ))}
      </div>
    </div>
  );
}

function ErrorState({ error, onRetry, onClose }) {
  const message =
    (typeof error === "string" && error) ||
    error?.message ||
    "The clip record could not be loaded.";
  return (
    <div className="cat-d-error" role="alert">
      <p className="cat-d-error__head">Could not load this clip</p>
      <p className="cat-d-error__body">{message}</p>
      <div className="cat-d-error__row">
        <button type="button" className="cat-btn cat-btn--solid" onClick={() => onRetry?.()}>
          <RotateCw size={14} aria-hidden="true" />
          <span>Retry</span>
        </button>
        <button type="button" className="cat-btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

/* lower_snake_case -> Sentence case, for the breadcrumb only. */
function humanise(value) {
  if (!value) return value;
  const spaced = String(value).replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
