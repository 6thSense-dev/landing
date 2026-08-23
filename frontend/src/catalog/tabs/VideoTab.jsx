/**
 * VideoTab — the dark media panel of the clip modal.
 * ---------------------------------------------------------------------------
 * Props: { clip, onViewChange }
 *   clip          the full 6s-clip/1.0 record
 *   onViewChange  optional; called with the active view id. ClipDetail draws
 *                 the eye labels over this surface and has to drop them over a
 *                 composite, and there is no other way for it to know.
 *
 * A clip can ship more than one thing to watch, and the buyer chooses:
 *
 *   overlay  media.video.overview  the rendered composite — the camera frame
 *            with both modelled palms, the 22x22 raw readout grid and the
 *            per-finger force bars drawn over it, moving with the video. It is
 *            the only view in which the tactile stream is visible at all, so it
 *            leads when it ships. Pre-composed, so it plays WHOLE: its own
 *            mode, no hairline, no eye labels.
 *   feed     the camera, chosen in the order the contract defines the fields:
 *            1. media.video.stereo_sbs   one file, both eyes, split by a hairline in CSS
 *            2. media.video.mono         one file, one eye
 *            3. media.video.left + right two files, played as a synchronised pair:
 *               the LEFT element is the clock, the right one is muted and is corrected
 *               whenever it drifts more than SYNC_TOLERANCE_S, and hard-reset on seek.
 *
 * media.video.closeup is offered as a LINK rather than a third view: it is one
 * taxel at 1/16 speed, so playing it in this element would put the timecode and
 * the segment ribbon on a timeline that is not the clip's.
 *
 * Controls are hand-built to match the reference: play/pause, mono elapsed, a
 * real <input type="range"> scrubber (so it is keyboard- and AT-operable, with
 * aria-valuetext read out as M:SS), mono total, fullscreen. Under the scrubber
 * is a proportional ribbon of clip.segments; clicking a segment seeks to it.
 *
 * Keyboard, only while focus is inside the media surface (which carries
 * data-arrowkeys="own" so ClipDetail does not steal Left/Right for clip
 * navigation):  Space play/pause · Left/Right +-5 s · Up/Down volume · M mute.
 *
 * Incoming seeks (see ClipDetail's header):
 *   window event "6s-catalog:seek" { clipId, t_s }   — heard live
 *   window.__6sCatalogSeek = { clipId, t_s, at }     — drained on mount, for
 *                                                      the case where the tab
 *                                                      was not yet rendered.
 *
 * PRESIGNED URLS ROTATE, AND `src` IS NOT BOUND TO THEM.
 *
 * Every silent refresh hands this component a new clip record whose media URLs
 * carry fresh signatures. Writing one into `<video src>` invokes the HTML media
 * load algorithm, which resets currentTime to 0 and pauses — so a buyer 30 s
 * into a 45 s clip is thrown back to the start, with no error to explain it.
 * Three unrelated things trigger that: the scheduled refresh at staleAt, any
 * poster 403 anywhere on the page (notifyAssetExpired zeroes every entry's
 * clock), and this element's own onError.
 *
 * So the source is managed imperatively, keyed on the OBJECT (origin + path)
 * rather than on the whole URL:
 *
 *   - the object changed  -> attach it and start from the beginning; it is a
 *                            different clip or a different encode.
 *   - only the signature  -> do nothing. The element keeps playing the URL it
 *     changed                already opened. The fresh URL is parked in a ref.
 *   - the element errors  -> the signature it holds really has died: adopt the
 *                            parked URL, restore currentTime, and resume if it
 *                            was playing.
 *
 * Which means a re-sign is invisible, and a genuine expiry costs one reload
 * that lands back at the same second.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Maximize2, Minimize2, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { assetUrl, notifyAssetExpired } from "../useCatalog.js";
import { formatDuration } from "../format.js";
import { PillGroup } from "./ImuTab.jsx";

const SEEK_EVENT = "6s-catalog:seek";
const SEEK_MAILBOX = "__6sCatalogSeek";
const MAILBOX_MAX_AGE_MS = 8000;
const SYNC_TOLERANCE_S = 0.12;

/* A clip with nothing playable. Held as one object so the render path can read
   `mode` unconditionally. */
const NO_VIEW = { mode: "none", primary: null, secondary: null };

function rel(url) {
  if (!url) return null;
  try {
    return assetUrl(url);
  } catch {
    return null;
  }
}

/**
 * WHICH object a URL points at, ignoring the signature.
 *
 * Two presigned URLs for the same S3 key differ only in their query string. That
 * difference must not restart playback, and a difference in the PATH must.
 */
function objectKey(url) {
  if (typeof url !== "string" || url === "") return null;
  const base = typeof window !== "undefined" ? window.location.href : "http://localhost/";
  try {
    const u = new URL(url, base);
    return `${u.origin}${u.pathname}`;
  } catch {
    return url.split("?")[0];
  }
}


/**
 * Every view this clip can be watched in, best first.
 *
 * The overlay leads on purpose: a buyer who presses nothing should see the
 * tactile stream moving with the video, which is the thing being sold. At most
 * two entries come back — there is one camera view, whichever files it takes.
 */
function pickViews(clip) {
  const v = clip?.media?.video;
  if (!v) return [];
  const out = [];
  if (v.overview) {
    out.push({ id: "overlay", label: "Tactile overlay", mode: "overlay",
               primary: rel(v.overview), secondary: null });
  }
  if (v.stereo_sbs) {
    out.push({ id: "feed", label: "Stereo feed", mode: "sbs",
               primary: rel(v.stereo_sbs), secondary: null });
  } else if (v.mono) {
    out.push({ id: "feed", label: "Camera feed", mode: "mono",
               primary: rel(v.mono), secondary: null });
  } else if (v.left && v.right) {
    out.push({ id: "feed", label: "Stereo feed", mode: "pair",
               primary: rel(v.left), secondary: rel(v.right) });
  } else if (v.left || v.right) {
    out.push({ id: "feed", label: "Camera feed", mode: "mono",
               primary: rel(v.left || v.right), secondary: null });
  }
  // rel() returns null for a URL the data layer cannot resolve, and a view with
  // no file is not a view — offering it would be a switch onto a black panel.
  return out.filter((view) => view.primary);
}

export default function VideoTab({ clip, onViewChange }) {
  const leftRef = useRef(null);
  const rightRef = useRef(null);
  const surfaceRef = useRef(null);
  const scrubbingRef = useRef(false);
  /* A seek asked for before the element knows its duration. Browsers drop a
     currentTime write at readyState 0, so it is replayed on loadedmetadata. */
  const pendingSeekRef = useRef(null);
  /* Set when a source is re-attached mid-playback: the loadedmetadata handler
     presses play again after it has replayed pendingSeekRef. */
  const resumeRef = useRef(false);
  /* The freshest URLs we have been handed, signature and all. Read at the
     moment a source is actually attached, never bound to `src` in JSX. */
  const srcRef = useRef({ primary: null, secondary: null });
  /* Set when the user switches VIEW. The overlay and the feed are two files on
     ONE timeline, so the playhead and the play state carry across the swap —
     the same restore path a rotated signature takes. */
  const carryRef = useRef(false);

  const views = useMemo(() => pickViews(clip), [clip]);
  const [viewId, setViewId] = useState(null);
  /* Resolved every render rather than stored: arrowing to a clip that does not
     ship the selected view falls back to its best one instead of emptying the
     panel, with no effect to reconcile the two. */
  const view = views.find((v) => v.id === viewId) || views[0] || null;
  const { mode, primary, secondary } = view || NO_VIEW;
  const poster = useMemo(() => (clip?.poster ? rel(clip.poster) : null), [clip]);
  const closeup = useMemo(() => rel(clip?.media?.video?.closeup), [clip]);
  srcRef.current = { primary, secondary };
  const primaryKey = objectKey(primary);
  const secondaryKey = objectKey(secondary);

  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(
    Number.isFinite(clip?.duration_s) ? clip.duration_s : 0
  );
  const [fullscreen, setFullscreen] = useState(false);

  const segments = Array.isArray(clip?.segments) ? clip.segments : [];
  const total = duration > 0 ? duration : clip?.duration_s || 0;

  /* ---------------- source attachment ---------------- */

  /**
   * Point an element at `url`.
   *
   * `restore` is the whole difference between a re-sign and a channel change:
   * with it, the position and the play state survive the reload; without it the
   * element starts at 0, which is right for a genuinely different object.
   */
  const attach = useCallback((el, url, restore) => {
    if (!el) return;
    if (!url) {
      el.removeAttribute("src");
      el.load();
      return;
    }
    if (el.getAttribute("src") === url) return;
    const at = restore ? el.currentTime : 0;
    const wasPlaying = restore && !el.paused && !el.ended;
    el.setAttribute("src", url);
    el.load();
    if (at > 0) pendingSeekRef.current = at;
    if (wasPlaying) resumeRef.current = true;
  }, []);

  /* A different object -> attach it from the beginning, unless it is the other
     view of the same clip, which keeps the position. Keyed on the object, NOT
     on the URL, so a rotated signature does not land here at all. */
  useEffect(() => {
    attach(leftRef.current, srcRef.current.primary, carryRef.current);
    carryRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryKey, attach]);

  useEffect(() => {
    attach(rightRef.current, srcRef.current.secondary, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondaryKey, attach]);

  /* The eye labels are drawn by ClipDetail, over this surface. Which view is
     playing decides whether they are true, so it has to hear about it. */
  useEffect(() => {
    onViewChange?.(view ? view.id : null);
  }, [view, onViewChange]);

  /**
   * The signature this element holds has died. Tell the data layer (so the
   * record is refetched) and, if a fresher URL for the same object has already
   * arrived, adopt it without losing the playhead.
   */
  const onMediaError = useCallback(
    (which) => {
      const el = which === "primary" ? leftRef.current : rightRef.current;
      const fresh = srcRef.current[which];
      notifyAssetExpired(el?.currentSrc || el?.getAttribute("src") || fresh);
      if (el && fresh && el.getAttribute("src") !== fresh) attach(el, fresh, true);
    },
    [attach]
  );

  /* ---------------- transport ---------------- */

  const seek = useCallback(
    (seconds) => {
      const l = leftRef.current;
      if (!l) return;
      const max = Number.isFinite(l.duration) && l.duration > 0 ? l.duration : total || 0;
      const next = Math.min(Math.max(seconds, 0), max || seconds);
      l.currentTime = next;
      const r = rightRef.current;
      if (r) r.currentTime = next;
      // readyState 0 means no metadata yet and the write above was ignored.
      if (l.readyState < 1) pendingSeekRef.current = next;
      setT(next);
    },
    [total]
  );

  const togglePlay = useCallback(() => {
    const l = leftRef.current;
    if (!l) return;
    if (l.paused) {
      l.play().catch(() => setPlaying(false));
    } else {
      l.pause();
    }
  }, []);

  const nudgeVolume = useCallback((delta) => {
    const l = leftRef.current;
    if (!l) return;
    l.volume = Math.min(1, Math.max(0, l.volume + delta));
    if (l.volume > 0 && l.muted) {
      l.muted = false;
      setMuted(false);
    }
  }, []);

  const toggleMute = useCallback(() => {
    const l = leftRef.current;
    if (!l) return;
    l.muted = !l.muted;
    setMuted(l.muted);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const node = surfaceRef.current;
    if (!node) return;
    if (document.fullscreenElement) {
      document.exitFullscreen?.().catch(() => {});
    } else {
      node.requestFullscreen?.().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  /* ---------------- the left element is the clock ---------------- */

  useEffect(() => {
    const l = leftRef.current;
    if (!l) return undefined;

    const syncSecondary = (hard) => {
      const r = rightRef.current;
      if (!r) return;
      const drift = Math.abs(r.currentTime - l.currentTime);
      if (hard || drift > SYNC_TOLERANCE_S) r.currentTime = l.currentTime;
    };

    const onTime = () => {
      if (!scrubbingRef.current) setT(l.currentTime);
      syncSecondary(false);
    };
    const onMeta = () => {
      if (Number.isFinite(l.duration) && l.duration > 0) setDuration(l.duration);
      const pending = pendingSeekRef.current;
      if (pending != null) {
        pendingSeekRef.current = null;
        l.currentTime = pending;
        const r = rightRef.current;
        if (r) r.currentTime = pending;
        setT(pending);
      }
      /* Re-attached mid-playback (a dead signature swapped for a live one).
         The position has just been restored above; press play again so the
         rotation is invisible rather than a silent stop. */
      if (resumeRef.current) {
        resumeRef.current = false;
        l.play().catch(() => setPlaying(false));
      }
    };
    const onPlay = () => {
      setPlaying(true);
      const r = rightRef.current;
      if (r) {
        syncSecondary(true);
        r.play().catch(() => {});
      }
    };
    const onPause = () => {
      setPlaying(false);
      rightRef.current?.pause();
    };
    const onSeeked = () => {
      syncSecondary(true);
      setT(l.currentTime);
    };
    const onVolume = () => setMuted(l.muted);
    const onEnded = () => setPlaying(false);

    l.addEventListener("timeupdate", onTime);
    l.addEventListener("loadedmetadata", onMeta);
    l.addEventListener("durationchange", onMeta);
    l.addEventListener("play", onPlay);
    l.addEventListener("pause", onPause);
    l.addEventListener("seeked", onSeeked);
    l.addEventListener("volumechange", onVolume);
    l.addEventListener("ended", onEnded);
    return () => {
      l.removeEventListener("timeupdate", onTime);
      l.removeEventListener("loadedmetadata", onMeta);
      l.removeEventListener("durationchange", onMeta);
      l.removeEventListener("play", onPlay);
      l.removeEventListener("pause", onPause);
      l.removeEventListener("seeked", onSeeked);
      l.removeEventListener("volumechange", onVolume);
      l.removeEventListener("ended", onEnded);
    };
    // Keyed on the OBJECTS, not the URLs: a rotated signature changes neither
    // element identity nor which handlers belong on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryKey, secondaryKey]);

  /* ---------------- incoming seek requests ---------------- */

  useEffect(() => {
    function apply(detail) {
      if (!detail) return;
      if (detail.clipId && clip?.id && detail.clipId !== clip.id) return;
      if (!Number.isFinite(detail.t_s)) return;
      seek(detail.t_s);
    }

    // Drain the mailbox: Segcap may have asked before this tab existed.
    // apply() is safe at readyState 0 — seek() parks the value and the
    // loadedmetadata handler replays it.
    const pending = typeof window !== "undefined" ? window[SEEK_MAILBOX] : null;
    if (pending && Date.now() - (pending.at || 0) < MAILBOX_MAX_AGE_MS) {
      window[SEEK_MAILBOX] = null;
      apply(pending);
    }

    const onEvent = (event) => apply(event.detail);
    window.addEventListener(SEEK_EVENT, onEvent);
    return () => window.removeEventListener(SEEK_EVENT, onEvent);
  }, [clip?.id, seek]);

  /* ---------------- keyboard, scoped to the surface ---------------- */

  const onSurfaceKeyDown = useCallback(
    (event) => {
      const target = event.target;
      const isRange = target instanceof HTMLElement && target.tagName === "INPUT";
      /* The scrubber and the view switch both step themselves on the arrow
         keys. Seeking or changing the volume as well would move two things
         with one press. */
      const ownsArrows =
        isRange ||
        (target instanceof HTMLElement && target.closest('[role="radiogroup"]') !== null);
      switch (event.key) {
        case " ":
        case "Spacebar":
          if (target instanceof HTMLElement && target.tagName === "BUTTON") return;
          event.preventDefault();
          togglePlay();
          break;
        case "ArrowLeft":
          if (ownsArrows) return;
          event.preventDefault();
          seek((leftRef.current?.currentTime ?? 0) - 5);
          break;
        case "ArrowRight":
          if (ownsArrows) return;
          event.preventDefault();
          seek((leftRef.current?.currentTime ?? 0) + 5);
          break;
        case "ArrowUp":
          if (ownsArrows) return;
          event.preventDefault();
          nudgeVolume(0.1);
          break;
        case "ArrowDown":
          if (ownsArrows) return;
          event.preventDefault();
          nudgeVolume(-0.1);
          break;
        case "m":
        case "M":
          event.preventDefault();
          toggleMute();
          break;
        default:
          break;
      }
    },
    [nudgeVolume, seek, toggleMute, togglePlay]
  );

  /* ---------------- render ---------------- */

  if (mode === "none" || !primary) {
    return (
      <div className="cat-v-empty">
        <p className="cat-v-empty__head">No video ships with this clip</p>
        <p className="cat-v-empty__body">
          <code>media.video</code> is null in the record, so there is nothing to play. The other
          tabs still describe everything the package contains.
        </p>
      </div>
    );
  }

  const altName = `${clip.title}, still frame`;
  const pct = total > 0 ? (t / total) * 100 : 0;

  return (
    /* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */
    <div
      className="cat-v"
      ref={surfaceRef}
      data-arrowkeys="own"
      tabIndex={0}
      onKeyDown={onSurfaceKeyDown}
      aria-label={`Video player for ${clip.title}. Space plays, arrow keys seek and change volume, M mutes.`}
      role="group"
    >
      <div className={`cat-v-stage cat-v-stage--${mode}`}>
        {/* No `src` attribute here on purpose — see the header. React
            re-rendering a rotated presigned URL into it would reset
            currentTime to 0 and pause, mid-clip, with nothing on screen to
            explain it. The effect above attaches the source instead, and only
            when the OBJECT changes.

            No crossOrigin attribute either: the source is a presigned S3 URL,
            nothing reads its pixels, and "anonymous" would make playback depend
            on the bucket's CORS config for no benefit. */}
        <video
          ref={leftRef}
          className="cat-v-el"
          /* The poster is a still of the CAMERA feed, so behind the composite it
             is a first frame at the wrong size, which jumps the moment play
             starts. Better one black frame than a visible correction. */
          poster={(mode === "overlay" ? null : poster) || undefined}
          preload="metadata"
          playsInline
          onError={() => onMediaError("primary")}
          aria-label={altName}
        />
        {mode === "pair" && secondary ? (
          <video
            ref={rightRef}
            className="cat-v-el"
            poster={poster || undefined}
            preload="metadata"
            playsInline
            muted
            onError={() => onMediaError("secondary")}
            aria-hidden="true"
            tabIndex={-1}
          />
        ) : null}
        {mode === "sbs" && !String(clip?.media?.video?.layout || "").startsWith("top_bottom") ? (
          <span className="cat-v-split" aria-hidden="true" />
        ) : null}
        {mode === "pair" ? <span className="cat-v-split cat-v-split--pair" aria-hidden="true" /> : null}
      </div>

      <div className="cat-v-controls">
        <button
          type="button"
          className="cat-v-btn cat-v-btn--play"
          onClick={togglePlay}
          aria-label={playing ? `Pause ${clip.title}` : `Play ${clip.title}`}
        >
          {playing ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
        </button>

        <span className="cat-v-time" aria-hidden="true">
          {formatDuration(t)}
        </span>

        <div className="cat-v-track">
          <input
            className="cat-v-range"
            type="range"
            min={0}
            max={total || 0}
            step={0.01}
            value={Math.min(t, total || 0)}
            aria-label={`Seek within ${clip.title}`}
            aria-valuetext={`${formatDuration(t)} of ${formatDuration(total)}`}
            onPointerDown={() => {
              scrubbingRef.current = true;
            }}
            onPointerUp={() => {
              scrubbingRef.current = false;
            }}
            onChange={(e) => {
              const next = Number(e.target.value);
              setT(next);
              seek(next);
            }}
            style={{ "--cat-v-pct": `${pct}%` }}
          />
          <SegmentRibbon segments={segments} total={total} onSeek={seek} current={t} />
        </div>

        <span className="cat-v-time" aria-hidden="true">
          {formatDuration(total)}
        </span>

        <button
          type="button"
          className="cat-v-btn"
          onClick={toggleMute}
          aria-label={muted ? "Unmute" : "Mute"}
        >
          {muted ? <VolumeX size={15} aria-hidden="true" /> : <Volume2 size={15} aria-hidden="true" />}
        </button>

        <button
          type="button"
          className="cat-v-btn"
          onClick={toggleFullscreen}
          aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        >
          {fullscreen ? (
            <Minimize2 size={15} aria-hidden="true" />
          ) : (
            <Maximize2 size={15} aria-hidden="true" />
          )}
        </button>
      </div>

      {views.length > 1 || closeup ? (
        <div className="cat-v-views">
          {views.length > 1 ? (
            <PillGroup
              label="Video view"
              value={view.id}
              onChange={(next) => {
                carryRef.current = true;
                setViewId(next);
              }}
              options={views.map((v) => ({ value: v.id, label: v.label }))}
            />
          ) : null}
          {closeup ? (
            <a
              className="cat-v-aside"
              href={closeup}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={`Open the force transient close-up for ${clip.title} in a new tab`}
            >
              Force transient close-up, 16x
              <ArrowUpRight size={13} aria-hidden="true" />
            </a>
          ) : null}
        </div>
      ) : null}

      {mode === "overlay" ? (
        <p className="cat-v-note">
          Both palms, the 22x22 readout grid and the force bars are rendered from the tactile
          arrays this take delivers, frame for frame with the video. Nothing here is drawn by
          hand, and the camera view is the same clip with none of it.
        </p>
      ) : null}

      {mode === "pair" ? (
        <p className="cat-v-note">
          Two separately encoded eyes. The left eye is the clock; the right is corrected whenever it
          drifts more than {Math.round(SYNC_TOLERANCE_S * 1000)} ms. Frame-exact stereo work should
          index <code>frame_times.csv</code>, not the container.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Proportional segment ribbon under the scrubber. Every segment is a real
 * button so the sub-task timeline is reachable without a pointer.
 */
function SegmentRibbon({ segments, total, onSeek, current }) {
  if (!segments.length || !(total > 0)) return null;
  return (
    <div className="cat-v-ribbon" role="group" aria-label="Annotated segments">
      {segments.map((s) => {
        const t0 = Math.max(0, Number(s.t0_s) || 0);
        const t1 = Math.max(t0, Number(s.t1_s) || t0);
        const left = (t0 / total) * 100;
        const width = Math.max(0.4, ((t1 - t0) / total) * 100);
        const live = current >= t0 && current < t1;
        return (
          <button
            key={`${s.index}-${t0}`}
            type="button"
            className={`cat-v-seg${live ? " is-live" : ""}`}
            style={{ left: `${left}%`, width: `${width}%` }}
            onClick={() => onSeek(t0)}
            title={`${s.label} — ${formatDuration(t0)}–${formatDuration(t1)}`}
            aria-label={`Seek to segment ${s.index + 1}, ${s.label}, at ${formatDuration(t0)}`}
          >
            <span className="cat-sr">{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}
