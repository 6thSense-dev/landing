/**
 * ClipCard — one clip summary as a single button.
 *
 * Contract notes (6s-catalog/1.0):
 *  - `clip` is a ClipSummary. Every key except poster/preview/detail is present; a value of
 *    null means "the ingest could not determine this" and renders as an em-dash, never as 0.
 *  - `clip.poster` / `clip.preview` may be ABSENT, which per the contract means "expand
 *    collection.paths.*". Resolution goes through the shared clipAssetPath() so the presence
 *    rule lives in exactly one place. Pass the optional `collection` prop (catalog.collection)
 *    to make templated manifests resolve; without it, an absent key behaves like null and the
 *    card draws its placeholder tile rather than a broken image.
 *
 * What the card says, and why (corpus of 2026-08: every clip is egocentric stereo + tactile,
 * recorded in China or Hong Kong):
 *
 *  - The old VIDEO · IMU · TACTILE · SEGCAP chip row is GONE. When every clip carries the same
 *    four modalities the row is the same on all 29 cards, so it distinguishes nothing and costs
 *    a line of vertical rhythm on every card. The modality facet in the filter bar still exists
 *    for the day the corpus is mixed again; the card now spends that line on two facts that
 *    genuinely vary per clip:
 *      1. USABLE TACTILE — qa.tactile_coverage as the headline figure with the per-hand
 *         qa.usable_channels census beside it and a hairline meter under it. This is the
 *         differentiator of the product AND the number a buyer discounts the price by: a 22x22
 *         glove has 484 readout sites and can easily have only 274 working channels.
 *      2. QA GRADE — qa.grade plus the checks_warn / checks_fail counts. "accepted" is true of
 *         every published clip so it is NOT rendered as a chip (it is in the tooltip and the
 *         accessible description); a disposition other than accepted IS rendered, because then
 *         it is news.
 *    A per-clip sync error was considered and rejected: ClipSummary carries no sync field.
 *    `sync.maximum_alignment_error_ms` lives on the clip DETAIL record and
 *    `totals.sync_max_alignment_error_ms` on the collection, so putting it on a card would mean
 *    one detail fetch per card. It is one click away in the Calibration & sync tab.
 *  - The thumbnail carries ONE always-on mark naming WHICH PRODUCT the clip is. The version
 *    this replaced marked only the anomaly — a `Mono` badge when `capture` was anything but
 *    stereo — on the reasoning that a uniform marker distinguishes nothing. That is true of a
 *    FILTER and false of a CLAIM: a buyer scanning thirty thumbnails was never told what they
 *    were looking at anywhere in the grid. It is now driven by presence: the mark states what
 *    the clip IS.
 *
 *    The rig ships TWO products and they are equals — "Stereo · Tactile" (camera plus two
 *    gloves) and "Stereo · Camera only" (camera, no gloves). Both get the same quiet pill.
 *    The version before this one rendered camera-only in the ALERT tone with a warning
 *    triangle and the words "No tactile", which described a sellable product as a defect on
 *    the first surface a buyer sees. Absence is only marked when it really is a fault: a clip
 *    that is not stereo (mono is not a product here), or a clip that says a glove was worn and
 *    then publishes no census for it. Those are the two states where something is wrong;
 *    shipping without gloves is not one of them.
 *  - Country renders as a NAME ("China"), never the alpha-2 code. See countryLabel() below.
 *  - "Channel yield" is the SAME quantity, under the SAME name, as the header tile and the
 *    Metadata tab. It used to be "Usable tactile" here (a percentage), "Usable tactile" on the
 *    header (a duration) and "Usable channels" in the modal — one label over two different
 *    quantities across three surfaces.
 *
 * Accessibility: the whole card is ONE button. There are deliberately no nested interactive
 * elements — the play affordance, the meter and the QA chips are decorative spans. Because the
 * button carries an aria-label, its inner text is not announced, so the extra facts (capture
 * class, tactile census, QA, one-line description) are exposed through aria-describedby.
 */
import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Play, ImageOff, AlertTriangle } from "lucide-react";
import { dash, formatDuration, formatPercent, labelize } from "./format.js";
import { assetUrl, clipAssetPath, notifyAssetExpired } from "./useCatalog.js";

/* ---------------------------------------------------------------- reduced motion

   One matchMedia listener for the whole grid. framer-motion's useReducedMotion would add a
   subscription per component, and this file is instantiated up to 1000 times. */

const RM_QUERY = "(prefers-reduced-motion: reduce)";
const rmSubs = new Set();
let rmMql = null;
let rmValue = false;
let rmReady = false;

function rmEnsure() {
  if (rmReady) return;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    rmReady = true;
    return;
  }
  rmReady = true;
  rmMql = window.matchMedia(RM_QUERY);
  rmValue = rmMql.matches;
  const onChange = () => {
    rmValue = rmMql.matches;
    rmSubs.forEach((cb) => cb());
  };
  if (typeof rmMql.addEventListener === "function") rmMql.addEventListener("change", onChange);
  else if (typeof rmMql.addListener === "function") rmMql.addListener(onChange);
}

function rmSubscribe(cb) {
  rmEnsure();
  rmSubs.add(cb);
  return () => rmSubs.delete(cb);
}
function rmSnapshot() {
  rmEnsure();
  return rmValue;
}
function rmServerSnapshot() {
  return false;
}

/** Shared `prefers-reduced-motion: reduce` flag. Exported so a second consumer in this folder
 *  subscribes to the same store rather than adding one listener per card. */
export function useReducedMotion() {
  return useSyncExternalStore(rmSubscribe, rmSnapshot, rmServerSnapshot);
}

/* ------------------------------------------------------- one preview loop at a time */

let activeRelease = null;

function claimPreview(release) {
  if (activeRelease && activeRelease !== release) activeRelease();
  activeRelease = release;
}
function dropPreview(release) {
  if (activeRelease === release) activeRelease = null;
}

/* -------------------------------------------------------------------- country names */

/**
 * Alpha-2 -> English name, for the two countries this corpus is recorded in.
 *
 * THE INGEST IS THE BETTER HOME FOR THIS. `facets.country[].label` already carries the
 * display name ("China" for CN) precisely so the UI carries no lookup table that can drift,
 * and the schema says so in as many words. Pass those labels down through
 * CatalogGrid's `countryLabels` prop and this map is never consulted.
 *
 * It exists as a floor, not as a policy: the card must never fall back to printing a bare
 * "CN" at a buyer. It is deliberately NOT a full ISO table and deliberately NOT a
 * locale-guessing library — an unmapped code renders as itself, which makes a corpus that
 * has drifted outside China / Hong Kong visible instead of quietly plausible.
 */
export const COUNTRY_NAMES = Object.freeze({
  CN: "China",
  HK: "Hong Kong",
});

/**
 * Display name for a ClipSummary.country.
 * null (ingest could not determine it) -> em-dash, per the format.js contract.
 */
export function countryLabel(code, labels) {
  if (code == null || code === "") return dash(null);
  if (labels && typeof labels[code] === "string" && labels[code]) return labels[code];
  return COUNTRY_NAMES[code] || code;
}

/* ------------------------------------------------------------------------ constants */

const EMPTY_LABELS = Object.freeze({});

/* Nominal poster geometry, used only when the clip reports no resolution. A poster is an
   already-composited [left | right] pair, so it is ~16:5. There is no second geometry: the
   thumb has one aspect ratio, and a record that is not a stereo pair is a data fault the
   card SAYS rather than silently relaying out into the grid rhythm. */
const NOMINAL_POSTER = [1920, 600];

function humanize(v) {
  return typeof v === "string" && v ? v.replace(/_/g, " ") : v;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function isNum(n) {
  return typeof n === "number" && Number.isFinite(n);
}

/* --------------------------------------------------------------------------- card */

function ClipCard({ clip, onOpen, collection, countryLabels = EMPTY_LABELS }) {
  const reduced = useReducedMotion();
  const descId = useId();
  const videoRef = useRef(null);
  const [previewOn, setPreviewOn] = useState(false);

  const stereo = clip.capture === "stereo_egocentric";
  /* Which product this is. `hands: []` is legal, determined and NOT null (CONTRACT §4). */
  const wornHands = useMemo(() => (Array.isArray(clip.hands) ? clip.hands : []), [clip.hands]);
  const posterPath = clipAssetPath(clip, "poster", collection);
  const previewPath = clipAssetPath(clip, "preview", collection);
  const posterSrc = posterPath ? assetUrl(posterPath) : null;
  const previewSrc = previewPath ? assetUrl(previewPath) : null;
  const canPreview = Boolean(previewSrc) && !reduced;

  const [posterW, posterH] = useMemo(() => {
    const r = clip.resolution;
    if (Array.isArray(r) && r.length === 2 && r[0] > 0 && r[1] > 0) return r;
    return NOMINAL_POSTER;
  }, [clip.resolution]);

  const durationText = formatDuration(clip.duration_s);
  const country = countryLabel(clip.country, countryLabels);

  /* ---- the two facts that vary per clip ---- */

  const qa = clip.qa || null;

  /**
   * H2/H4 tactile census. `tactile_coverage` is the published derived figure — usable
   * channels on the WORST hand over that hand's readout sites — so it is the one number
   * that compares honestly across clips, one-handed or two. The per-hand counts sit beside
   * it because "57%" of an unstated denominator is not a fact a buyer can act on.
   */
  const tactile = useMemo(() => {
    const uc = (qa && qa.usable_channels) || null;
    const left = uc && isNum(uc.left) ? uc.left : null;
    const right = uc && isNum(uc.right) ? uc.right : null;
    const cov = qa && isNum(qa.tactile_coverage) ? qa.tactile_coverage : null;
    const census = [];
    if (left != null) census.push(`L ${left}`);
    if (right != null) census.push(`R ${right}`);
    const present = cov != null || census.length > 0;
    /* `hands` is never null and [] is a determined answer, so it — not the absence of a
       census — is what says which of the two products this is. A clip that WORE a glove and
       published no census is a different, worse state and must not read the same. */
    const gloveless = wornHands.length === 0;
    return {
      present,
      gloveless,
      coverage: cov,
      headline: gloveless ? "n/a" : cov == null ? dash(null) : formatPercent(cov, 0),
      census: gloveless ? "no gloves" : census.length ? `${census.join(" · ")} ch` : null,
      /* clamped so a manifest that ever ships 1.0000001 cannot overflow the track */
      fill: cov == null ? null : `${Math.max(0, Math.min(1, cov)) * 100}%`,
      /* The definition, in the same words the header tile and the Metadata tab use:
         live-and-stable channels on the worst hand over that hand's readout sites. A
         percentage of an unstated denominator is not a fact a buyer can act on. */
      title: gloveless
        ? "Camera only: this package ships no tactile gloves, so there is no channel " +
          "census to report. `hands` is [] and the tactile QA checks read not_applicable " +
          "rather than not_run — there is nothing here that was left unmeasured."
        : !present
          ? "A glove was worn on this clip and it publishes no tactile channel census."
          : [
              left != null ? `${left} usable channels on the left glove` : null,
              right != null ? `${right} usable channels on the right glove` : null,
              cov == null
                ? null
                : `channel yield ${formatPercent(cov, 1)} of the worst hand's readout sites`,
            ]
              .filter(Boolean)
              .join(", ") + ".",
    };
  }, [qa, wornHands]);

  /**
   * H4 quality. Every clip in a published manifest is dispositioned `accepted`, so the word
   * alone says nothing and is not given a chip; the warn count is the part that distinguishes
   * one card from another, and a non-accepted disposition is news and IS given a chip.
   */
  const quality = useMemo(() => {
    if (!qa) return null;
    const warns = isNum(qa.checks_warn) ? qa.checks_warn : null;
    const fails = isNum(qa.checks_fail) ? qa.checks_fail : null;
    const odd = qa.disposition && qa.disposition !== "accepted" ? qa.disposition : null;
    /* qa.sync_validated: true when a common-mode PHYSICAL event corroborated this
       clip's stream alignment, false when nothing did, null when the clip ships no
       sync record. A grade shown without it lets the card imply a quality the sync
       record does not support — twenty of thirty clips in this corpus rest on clock
       arithmetic alone, and the only place that said so was the tail of the Calib &
       sync tab. Only the FALSE case is marked: "validated" is the expectation, and a
       chip on every card for the expectation is chrome. */
    const unvalidated = qa.sync_validated === false;
    return {
      grade: qa.grade || null,
      warns,
      fails,
      odd,
      unvalidated,
      clean: warns === 0 && (fails === 0 || fails == null),
      title: [
        qa.grade ? `Grade ${qa.grade}.` : null,
        qa.disposition ? `QA disposition: ${qa.disposition}.` : null,
        warns != null ? `${plural(warns, "check")} outside the preferred bound.` : null,
        fails ? `${fails} outside the acceptance bound.` : null,
        unvalidated
          ? "Stream alignment is NOT independently validated: no common-mode physical " +
            "event was staged in this take, so the alignment rests on the shared host clock."
          : qa.sync_validated === true
            ? "Stream alignment independently validated against a common-mode physical event."
            : null,
      ]
        .filter(Boolean)
        .join(" "),
    };
  }, [qa]);

  /**
   * The one always-on thumbnail mark: WHICH PRODUCT this clip is.
   *
   * Presence, not absence. Two products, one tone between them — egocentric stereo with
   * gloves and egocentric stereo without are both things this rig sells, so neither is
   * stamped as a defect. The alert tone is reserved for the two states that really are
   * defects: a clip that is not stereo (mono is not a product), and a clip that claims a
   * glove was worn and then publishes no census for it.
   */
  const mark = useMemo(() => {
    if (!stereo) {
      return {
        ok: false,
        text: "Not stereo",
        title:
          "This clip does not carry stereo video. Both products this rig ships are stereo, " +
          "so this is a data fault and not a variant.",
        speech: "Warning: this clip does not carry stereo video",
      };
    }
    if (tactile.gloveless) {
      return {
        ok: true,
        text: "Stereo · Camera only",
        title:
          "Egocentric stereo video, no tactile gloves. This is one of the two products " +
          "this rig ships, not a clip with something missing from it.",
        speech: "Egocentric stereo video, camera only",
      };
    }
    if (!tactile.present) {
      return {
        ok: false,
        text: "Census missing",
        title:
          "This clip says a tactile glove was worn and publishes no channel census for it. " +
          "That is a packaging fault, and it is not the same as the camera-only product.",
        speech: "Warning: a glove was worn on this clip and no tactile census was published",
      };
    }
    return {
      ok: true,
      text: "Stereo · Tactile",
      title: "Egocentric stereo video and two tactile gloves.",
      speech: "Egocentric stereo video with tactile",
    };
  }, [stereo, tactile.gloveless, tactile.present]);

  /* The accessible name is fixed by the design contract:
     "${title} — ${category}, ${country}, ${duration}". A null country is spoken rather than
     rendered as an em-dash, which a screen reader would announce as the word "dash". */
  const ariaLabel = `${clip.title} — ${humanize(clip.category)}, ${
    clip.country ? country : "country unknown"
  }, ${durationText}`;

  const ariaDescription = useMemo(() => {
    const parts = [mark.speech];
    if (tactile.present) parts.push(tactile.title.replace(/\.$/, ""));
    if (quality && quality.grade) {
      parts.push(
        `QA grade ${quality.grade}` +
          (qa && qa.disposition ? `, ${qa.disposition}` : "") +
          (quality.warns != null ? `, ${plural(quality.warns, "warning")}` : "") +
          (quality.fails ? `, ${plural(quality.fails, "failure")}` : "") +
          (quality.unvalidated ? ", alignment not independently validated" : ""),
      );
    }
    if (clip.description_short) parts.push(clip.description_short);
    return parts.join(". ");
  }, [mark, tactile, quality, qa, clip.description_short]);

  /* One object per clip rather than one per render: the grid is budgeted for 1000 cards. */
  const meterStyle = useMemo(
    () => (tactile.fill == null ? null : { "--cat-meter-fill": tactile.fill }),
    [tactile.fill],
  );

  const handleOpen = useCallback(() => {
    if (onOpen) onOpen(clip.id);
  }, [onOpen, clip.id]);

  const release = useCallback(() => setPreviewOn(false), []);

  const startPreview = useCallback(() => {
    if (!canPreview) return;
    claimPreview(release);
    setPreviewOn(true);
  }, [canPreview, release]);

  const stopPreview = useCallback(() => {
    dropPreview(release);
    setPreviewOn(false);
  }, [release]);

  /* Give up the "currently playing" slot if the card unmounts mid-hover. */
  useEffect(() => () => dropPreview(release), [release]);

  /* Reduced motion can be switched on while a loop is running. */
  useEffect(() => {
    if (reduced && previewOn) stopPreview();
  }, [reduced, previewOn, stopPreview]);

  /* Pause and unload on leave — unmounting alone leaves the fetch in flight in some engines. */
  useEffect(() => {
    if (!previewOn) return undefined;
    return () => {
      const v = videoRef.current;
      if (!v) return;
      try {
        v.pause();
        v.removeAttribute("src");
        v.load();
      } catch {
        /* teardown is best effort */
      }
    };
  }, [previewOn]);

  const handleCanPlay = useCallback((e) => {
    e.currentTarget.classList.add("is-ready");
  }, []);

  return (
    <button
      type="button"
      className="cat-card"
      aria-label={ariaLabel}
      aria-describedby={descId}
      onClick={handleOpen}
      onMouseEnter={startPreview}
      onMouseLeave={stopPreview}
      onFocus={startPreview}
      onBlur={stopPreview}
    >
      <span className={`cat-card__thumb${stereo ? " cat-card__thumb--stereo" : ""}`}>
        {posterSrc ? (
          <img
            className="cat-card__poster"
            src={posterSrc}
            width={posterW}
            height={posterH}
            loading="lazy"
            decoding="async"
            onError={() => notifyAssetExpired(posterSrc)}
            alt={`${clip.title}, still frame`}
          />
        ) : (
          <span className="cat-card__placeholder" aria-hidden="true">
            <ImageOff size={18} strokeWidth={1.5} />
            <span className="cat-card__placeholder-t">No poster</span>
          </span>
        )}

        {previewOn && previewSrc ? (
          <video
            ref={videoRef}
            className="cat-card__preview"
            src={previewSrc}
            muted
            loop
            playsInline
            autoPlay
            preload="none"
            tabIndex={-1}
            aria-hidden="true"
            onCanPlay={handleCanPlay}
          />
        ) : null}

        {/* The product, stated on every card. Quiet by design — 2xs semibold on a dark
            scrim, bottom-right, out of the way of the poster's own overlays — because it
            is a constant, and a constant that shouts is chrome. The alert tone is the
            same slot, and it is not quiet. */}
        <span
          className={`cat-card__mark${mark.ok ? "" : " cat-card__mark--alert"}`}
          title={mark.title}
          aria-hidden="true"
        >
          {mark.ok ? null : <AlertTriangle size={11} strokeWidth={2.2} />}
          <span className="cat-card__mark-t">{mark.text}</span>
        </span>

        <span className="cat-card__play" aria-hidden="true">
          <Play size={15} strokeWidth={2} fill="currentColor" />
        </span>
      </span>

      <span className="cat-card__body">
        <span className="cat-card__head">
          <span className="cat-card__title">{clip.title}</span>
          <span className="cat-card__country">{country}</span>
        </span>

        <span className="cat-card__meta">
          <span className="cat-card__sub">{labelize(clip.subcategory)}</span>
          <span className="cat-card__dur">{durationText}</span>
        </span>

        <span className="cat-card__specs">
          <span className="cat-card__spec cat-card__spec--tactile" title={tactile.title}>
            <span className="cat-card__spec-l">Channel yield</span>
            <span className="cat-card__spec-v">
              <span className="cat-card__figure">{tactile.headline}</span>
              {tactile.census ? <span className="cat-card__census">{tactile.census}</span> : null}
            </span>
            <span
              className={`cat-card__meter${meterStyle ? "" : " is-empty"}`}
              style={meterStyle || undefined}
              aria-hidden="true"
            />
          </span>

          {quality ? (
            <span className="cat-card__spec cat-card__spec--qa" title={quality.title}>
              <span className="cat-card__spec-l">QA grade</span>
              <span className="cat-card__spec-v">
                {quality.grade ? (
                  <span className="cat-card__grade" data-grade={quality.grade}>
                    {quality.grade}
                  </span>
                ) : null}
                {quality.odd ? (
                  <span className="cat-card__flag cat-card__flag--fail">{humanize(quality.odd)}</span>
                ) : null}
                {quality.fails ? (
                  <span className="cat-card__flag cat-card__flag--fail">
                    {plural(quality.fails, "fail")}
                  </span>
                ) : null}
                {quality.warns ? (
                  <span className="cat-card__flag">{plural(quality.warns, "warn")}</span>
                ) : null}
                {/* The fact that says what every alignment figure on this clip is
                    WORTH. Only the negative case is shown; see the memo above. */}
                {quality.unvalidated ? (
                  <span className="cat-card__flag cat-card__flag--unvalidated">unvalidated</span>
                ) : null}
                {quality.clean && !quality.odd && !quality.unvalidated ? (
                  <span className="cat-card__flag cat-card__flag--clean">clean</span>
                ) : null}
              </span>
            </span>
          ) : null}
        </span>
      </span>

      <span id={descId} hidden>
        {ariaDescription}
      </span>
    </button>
  );
}

/* Shallow comparator keyed on clip.id, per the grid's 1000-card budget. `onOpen` is compared
   too so a direct consumer that passes a fresh closure still gets a correct handler;
   CatalogGrid already hands down a stable one, so in practice only the id check runs. */
export default React.memo(
  ClipCard,
  (a, b) =>
    a.clip.id === b.clip.id &&
    a.onOpen === b.onOpen &&
    a.collection === b.collection &&
    a.countryLabels === b.countryLabels,
);
