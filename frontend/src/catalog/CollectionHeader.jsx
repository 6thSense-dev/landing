import React from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronRight,
  Download,
  Info,
  Mail,
  Scale,
} from "lucide-react";

import { assetUrl } from "./useCatalog.js";
import { dash, formatBytes, formatCount, formatHours, formatMinutes } from "./format.js";

/**
 * The collection masthead: what this drop is, what it costs you to look at
 * the rest of it, and the four figures a buyer scans for before anything else.
 *
 * Laid out as two columns, not one. The version this replaced ran a twelve-line
 * paragraph down a narrow left gutter with the entire right half of the page
 * empty and the primary CTA floating in it. Here the lede is capped at a 52ch
 * measure and the access block is a real card in the second column, so the
 * call to action is anchored to the thing it is asking about.
 *
 * The long paragraph is not gone — it is every word it was, inside a collapsed
 * "About this collection". What is promoted above it is `collection.standfirst`,
 * an AUTHORED field carrying one claim and one limit.
 *
 * It is authored because the version this replaced sliced it: standfirst(text,
 * {maxSentences: 2, maxChars: 260}) took sentence 1 unconditionally and dropped
 * sentence 2 when the pair exceeded the cap. That is a POSITION rule, and a
 * position rule promotes whatever the writer put first, which is always the
 * claim and never the limit. On the shipped description the cut was
 * deterministic: sentence 1 was 172 chars, sentence 2 was 281, so the buyer was
 * shown exactly one sentence — the only one in the paragraph with no
 * qualification in it — and "a capability sample and not a corpus" and "no
 * calibration into force units" went behind a disclosure they had to open. The
 * code comment said "the qualifications matter too much to be skimmed" and then
 * guaranteed they were never seen. The slicer is gone; see standfirst() below
 * for what remains of it and why.
 *
 * Totals come precomputed from the manifest so the header renders without
 * iterating clips[]. Where a total is null the ingest could not determine it,
 * and it renders as an em-dash — never as 0.
 *
 * @param {object}   props.collection      catalog.collection
 * @param {object}   props.totals          catalog.collection.totals
 * @param {number|null} [props.modalityCount]  distinct modalities across clips[].
 *   Not in `totals`, so the caller derives it from clips[] (the authority) and
 *   passes it down. Omit and the figure shows an em-dash.
 * @param {object|null} [props.countryLabels]  value -> display name for the country
 *   facet, straight out of facets.country[].label. Present so the figure reads
 *   "China · Hong Kong" rather than "CN · HK": the alpha-2 code is a join key, not
 *   a thing to show a buyer. Omit it and the codes are shown, which is honest but
 *   worse — never a hardcoded ISO table, which is what would drift.
 * @param {object|null} [props.derived]  the three figures a buyer negotiates on that
 *   `totals` does not carry, folded over clips[] by the caller (which holds the
 *   authority for anything totals and clips[] could disagree about):
 *   `{ training: {clips, minutes}, cleared: {clips, minutes}, census: {median, sites} }`.
 *   Omit and those tiles fall back to what totals alone can say.
 * @param {object|null} [props.access]  catalog.access — the level this account has,
 *   what was withheld from it, how to ask for the rest, and the preview notice.
 *   The API sends it on every response.
 * @param {() => void} [props.onRequestAccess]  overrides the mailto below. Optional:
 *   without it the CTA is an <a href="mailto:…"> built from the vendor contact, so
 *   the button always has a destination. If neither exists it is not rendered —
 *   a primary call to action that does nothing is worse than no button.
 */
export default function CollectionHeader({
  collection,
  totals,
  access = null,
  modalityCount = null,
  countryLabels = null,
  derived = null,
  onRequestAccess = null,
}) {
  const license = collection && collection.license ? collection.license : null;
  const vendor = collection && collection.vendor ? collection.vendor : null;
  const t = totals || {};

  /* Set by the ingest from each take's own declaration; `recorded` is the only
     value that does not need saying out loud. Read high up because it changes how
     the geography figure is LABELLED, not only whether a banner renders. */
  const provenance = collection ? collection.provenance_class : null;
  const generated = provenance === "synthetic" || provenance === "mixed";

  const countries = Array.isArray(t.countries) ? t.countries : null;
  const countryName = (code) =>
    (countryLabels && typeof countryLabels[code] === "string" && countryLabels[code]) || code;
  const countryNames = countries ? countries.map(countryName) : null;

  // `totals.*hours` are ALWAYS stored in hours; `totals.duration_unit` says which unit
  // to render them in (CONTRACT.md §3.1.1). A ~20 minute corpus resolves to `minutes`,
  // and showing "0.31 h" for it reads as a broken number. The conversion lives here and
  // nowhere else — the stored figures are never mutated.
  const inMinutes = t.duration_unit === "minutes";
  const dur = (h) => (inMinutes ? formatMinutes(h == null ? h : h * 60) : formatHours(h));
  const durLabel = inMinutes ? "Minutes" : "Hours";

  const splits = collection && collection.splits ? collection.splits : null;
  const sample = collection && collection.sample_archive ? collection.sample_archive : null;
  const sampleHref = sample ? assetUrl(sample.url) : null;

  /* H1, on the header rather than in the 29th detail record. The measured
     worst case is the number a buyer needs before they read anything else, and
     the count over one frame is what says whether it is an outlier or the shape
     of the corpus. Both come precomputed in `totals`; neither is derived here. */
  const syncMax = t.sync_max_alignment_error_ms;
  const overFrame = t.sync_clips_over_one_frame;
  const measured = t.sync_clips_measured;
  const validated = t.sync_clips_independently_validated;
  const clips = t.clips;
  const syncHint =
    syncMax == null
      ? "No clip in this collection published a measured inter-stream alignment error."
      : [
          `Worst measured inter-stream alignment error over ${formatCount(measured)} clip` +
            (measured === 1 ? "" : "s") + ".",
          t.sync_p95_alignment_error_ms != null
            ? `95th percentile ${formatMs(t.sync_p95_alignment_error_ms)}.`
            : null,
          overFrame != null
            ? `${formatCount(overFrame)} of ${formatCount(measured)} exceed one video frame.`
            : null,
          /* What the number MEANS, in the words the per-clip tab already uses. A
             buyer reading "56.74 ms" against a 33.33 ms frame has to do the
             division themselves to learn that a contact event is locatable to two
             frames, not one — which is the fact that decides whether a 246.5 Hz
             tactile stream is worth 246.5 Hz to them. */
          framesFor(syncMax) != null
            ? `In the worst clip a contact event is locatable to roughly ` +
              `${framesFor(syncMax)} video frames, not one.`
            : null,
          /* And what the number is WORTH. An alignment error is arithmetic over a
             shared host clock; only a common-mode physical event corroborates it. */
          validated != null && clips != null
            ? `${formatCount(validated)} of ${formatCount(clips)} clips are independently ` +
              `validated against a staged physical event; on the rest the alignment rests ` +
              `on the shared host clock alone.`
            : null,
        ]
          .filter(Boolean)
          .join(" ");

  const training = derived && derived.training ? derived.training : null;
  const cleared = derived && derived.cleared ? derived.cleared : null;
  const census = derived && derived.census ? derived.census : null;

  /* Channel yield as a FRACTION, from the two published totals: the
     coverage-weighted seconds over the seconds that carry tactile. It is the
     corpus-level version of the identical per-clip figure the card and the
     Metadata tab show, under the identical name. */
  const yieldFrac =
    t.tactile_hours && t.tactile_usable_hours != null && t.tactile_hours > 0
      ? t.tactile_usable_hours / t.tactile_hours
      : null;

  /*
   * Ranked, and cut to four.
   *
   * Eight tiles on one auto-fit row gave 136px columns at 1440, which wrapped
   * three of the labels and dropped their values off the shared baseline. The
   * fix is not smaller type: it is fewer tiles. Subjects / Countries /
   * Modalities / Total size are real but secondary, and sit in the summary row
   * under the strip.
   *
   * WHAT THE FOUR ARE, AND WHY THESE FOUR:
   *
   * 1. Training-licensed, not Clips. "30 clips" is on the filter bar four
   *    hundred pixels down and the tile said it again; what the page never said
   *    anywhere was how much of the corpus a lab could actually put in a
   *    training run. Counted off the manifest: model_training granted on 18 of
   *    30 clips, 11.5 of 19 minutes. Intersect that with commercial use,
   *    consent on file and a passed PII review and it is 12 clips / 7.8
   *    minutes. The headline overstated the trainable volume by 2.4x and the
   *    only way to find the real number was to click a rights facet and read a
   *    chip count — which reports clips, never minutes.
   *
   * 2. The duration. Unchanged.
   *
   * 3. Channel yield, not "Usable tactile 11.3 min". That figure was
   *    SUM(duration x worst-hand coverage) — a channel-weighted product
   *    presented as a duration, which invites the reading "11.3 minutes where
   *    the gloves work". No clip has 11.3 good minutes; the tactile is
   *    partially dead for the whole 19. Worse, "Usable tactile" also named a
   *    percentage on the card and "Usable channels" named the same percentage
   *    in the modal: one label over two quantities across three surfaces. It is
   *    now the same NAME for the same QUANTITY everywhere, with the
   *    channel-weighted minutes kept as the sub-line where it cannot be
   *    mistaken for wall clock.
   *
   * 4. Max sync error. Unchanged in value; its sub-line now carries the
   *    validation count, because a measured error nothing corroborates is a
   *    different product from one that is corroborated.
   *
   * At four columns the longest label ("TRAINING-LICENSED") fits on one line at
   * every width down to the 640px two-column breakpoint, so nothing is
   * abbreviated to make it fit.
   */
  const stats = [
    training
      ? {
          label: "Training-licensed",
          value: `${formatCount(training.clips)} clips`,
          sub:
            training.minutes != null
              ? `${fmtMinutes(training.minutes)}` +
                (cleared ? ` · ${formatCount(cleared.clips)} fully cleared` : "")
              : undefined,
          hint:
            "Clips whose rights.model_training reads `granted`, and their total duration. " +
            (cleared
              ? `Of those, ${formatCount(cleared.clips)} (${fmtMinutes(cleared.minutes)}) are ` +
                "also granted for commercial use with consent on file and a passed PII " +
                "review — the subset with no open question before a training run. "
              : "") +
            "Every other clip needs a conversation before it is used.",
        }
      : { label: "Clips", value: formatCount(clips) },
    {
      label: durLabel,
      value: dur(t.hours),
      sub: clips != null ? `${formatCount(clips)} clips` : undefined,
    },
    {
      // NOT a duration. See note 3 above.
      label: "Channel yield",
      value: yieldFrac == null ? dash(null) : `${Math.round(yieldFrac * 100)}%`,
      sub: census
        ? `median ${formatCount(census.median)} of ${formatCount(census.sites)} sites`
        : undefined,
      hint:
        yieldFrac == null
          ? "No clip in this collection published a tactile channel census."
          : "Live-and-stable channels on the worst hand, over that hand's readout sites, " +
            "weighted by clip duration. The same quantity, under the same name, as the " +
            "figure on every card and in every clip's Metadata tab. " +
            (t.tactile_usable_hours != null && t.tactile_hours != null
              ? `All ${dur(t.tactile_hours)} of wall clock carry tactile; weighted by ` +
                `working channels that is ${dur(t.tactile_usable_hours)}, which is a ` +
                "channel-weighted product and NOT minutes during which the gloves worked."
              : ""),
    },
    {
      // Never "about one frame". The measured maximum, or an em-dash.
      label: "Max sync error",
      value: formatMs(syncMax),
      hint: syncHint,
      sub: [
        overFrame != null && measured
          ? `${formatCount(overFrame)}/${formatCount(measured)} over one frame`
          : null,
        validated != null && clips != null
          ? `${formatCount(validated)}/${formatCount(clips)} validated`
          : null,
      ]
        .filter(Boolean)
        .join(" · ") || undefined,
    },
  ];

  /* The second rank. Deliberately NOT `.cat-stat`: a second row of tiles would
     put four more values on a second baseline, which is the exact defect the
     eight-tile row had. These are a figure list, read left to right. */
  const secondary = [
    { label: "Subjects", value: formatCount(t.subjects) },
    {
      // "Countries" on a corpus whose every clip is `provenance.media_class:
      // synthetic` is a fabricated attribute presented as an observation, one
      // line above a banner saying these are not recordings of a real workspace.
      // The field is still worth showing — it is what the takes DECLARE, and it
      // is what the country facet filters on — but it is labelled as declared
      // until the corpus is real, at which point this reverts on its own.
      label: generated ? "Locale (declared)" : "Countries",
      // At two or three, the NAMES are the answer and a count is a worse version
      // of it — "2" tells a buyer nothing, "China · Hong Kong" tells them whether
      // the corpus is in scope for them. Past three the count is the figure and
      // the names are the tooltip, because four names do not fit the slot.
      value:
        countryNames && countryNames.length && countryNames.length <= 3
          ? countryNames.join(" · ")
          : formatCount(countries ? countries.length : null),
      hint: generated
        ? "Declared by each take, not observed: this collection's media is generated, so " +
          "the location is an attribute of the scenario and not of a recording." +
          (countryNames && countryNames.length ? ` ${countryNames.join(" · ")}.` : "")
        : countryNames && countryNames.length
          ? countryNames.join(" · ")
          : undefined,
    },
    { label: "Modalities", value: formatCount(modalityCount) },
    { label: "Total size", value: formatBytes(t.bytes) },
  ];

  const licenseHref = license ? assetUrl(license.url) : null;

  /* The primary conversion action on the only page whose job is to start a
     procurement conversation. It gets a real destination or it does not ship. */
  const contact = vendor && typeof vendor.contact === "string" ? vendor.contact.trim() : "";
  const requestHref = contact ? mailtoFor(contact, collection) : null;
  const onRequest = typeof onRequestAccess === "function" ? onRequestAccess : null;

  const description =
    collection && typeof collection.description === "string" ? collection.description.trim() : "";
  /* AUTHORED. `collection.standfirst` carries one claim and one limit, written as
     a pair; see the note at the top of this file for what slicing the description
     did instead. A drop that authored none gets no promoted line — which is the
     honest failure, because the alternative is promoting an unqualified half of a
     paragraph and calling it a summary. */
  const lede = standfirst(collection);
  // Only worth a disclosure when there is more behind it than the standfirst
  // already shows.
  const hasMore = description !== "" && lede !== description;

  const name = collection && collection.name ? collection.name : "This collection";

  return (
    <header className="cat-masthead">
      <div className="cat-masthead__grid">
        {/* ---------- left: what this is ---------- */}
        <div className="cat-masthead__lede">
          {/* "Catalog" is gone as a word: the top bar already says where you
              are, and the collection's own name is the only heading that
              carries information. */}
          <h1 className="cat-display cat-masthead__title">
            {name}
            {collection && collection.version ? (
              <span className="cat-masthead__version cat-mono">v{collection.version}</span>
            ) : null}
          </h1>

          {/* .cat-lead is the system's one-per-surface lead paragraph: 52ch
              measure, light weight at md size, --ink at 12.7:1 on paper. */}
          {lede ? <p className="cat-lead">{lede}</p> : null}

          {hasMore ? (
            <details className="cat-disclosure">
              <summary className="cat-disclosure__summary">
                <ChevronRight className="cat-disclosure__chevron" size={14} aria-hidden="true" />
                About this collection
              </summary>
              {/* The producer's paragraph, whole. Nothing in it was edited to
                  make the page shorter — "a capability sample, not a corpus",
                  the sync caveat and "five operators, four rigs" are all still
                  here, verbatim, one click away instead of twelve lines up. */}
              <div className="cat-disclosure__body">
                <p>{description}</p>
              </div>
            </details>
          ) : null}
        </div>

        {/* ---------- right: how you get the rest of it ---------- */}
        <aside className="cat-card-surface cat-access" aria-label="Access and licence">
          <p className="cat-label cat-access__eyebrow">Access</p>

          {/* A handler wins if the host supplies one (a lead form, say); otherwise
              this is a plain anchor to the vendor's monitored role address. If
              there is neither, the button is not rendered at all — a primary call
              to action that does nothing is worse than no button. */}
          {onRequest ? (
            <button type="button" className="cat-btn cat-btn--primary" onClick={onRequest}>
              Request full access
              <ArrowUpRight size={16} aria-hidden="true" />
            </button>
          ) : requestHref ? (
            <a className="cat-btn cat-btn--primary" href={requestHref}>
              Request full access
              <ArrowUpRight size={16} aria-hidden="true" />
            </a>
          ) : null}

          {/* The API computes `access.how_to_request` on every response and it
              used to be read by nothing. A page that says "available on request"
              six times and never says how to make one is where a buyer leaves. */}
          {access && access.how_to_request ? (
            <p className="cat-access__how">
              <Mail size={13} aria-hidden="true" />
              {/* The API's copy already names the address in most collections.
                  Appending it again reads as a stutter, so the address is only
                  added when the sentence does not already carry it. */}
              <span>
                {contact && access.how_to_request.includes(contact) ? (
                  linkifyContact(access.how_to_request, contact, requestHref)
                ) : (
                  <>
                    {access.how_to_request}
                    {contact ? (
                      <>
                        {" "}
                        <a href={requestHref}>{contact}</a>
                      </>
                    ) : null}
                  </>
                )}
              </span>
            </p>
          ) : null}

          {license || sampleHref ? <div className="cat-access__rule" aria-hidden="true" /> : null}

          {license ? (
            <div className="cat-access__chips">
              {licenseHref ? (
                <a
                  className="cat-chip"
                  href={licenseHref}
                  target="_blank"
                  rel="noreferrer noopener"
                  title={license.summary || undefined}
                >
                  <Scale size={13} aria-hidden="true" />
                  <span>{license.name}</span>
                  <ArrowUpRight size={12} aria-hidden="true" />
                </a>
              ) : (
                <span className="cat-chip" title={license.summary || undefined}>
                  <Scale size={13} aria-hidden="true" />
                  <span>{license.name}</span>
                </span>
              )}
            </div>
          ) : null}

          {/* The open evaluation clip: a whole package, with a digest to verify,
              that a prospect can run through their own loader before talking to
              anyone. Absent when no fully-granted clip has been packaged. */}
          {sampleHref ? (
            <>
              <a className="cat-btn cat-btn--ghost" href={sampleHref} download>
                <Download size={15} aria-hidden="true" />
                <span>Download sample clip</span>
              </a>
              <p className="cat-access__sample">
                <b>{sample.clip_id}</b>
                {" · "}
                {sample.format}
                {" · "}
                {formatBytes(sample.bytes)}
                {sample.sha256 ? (
                  <>
                    {" · sha256 "}
                    {String(sample.sha256).slice(0, 16)}…
                  </>
                ) : null}
              </p>
            </>
          ) : null}

          {/* Named, not bare. Set in the same tracked-out semibold caps as every
              other micro-label in the card, an unlabelled "6THSENSE" underneath a
              licence chip read as a stray link rather than as the publisher —
              which is the one thing on this card a procurement reader has to be
              able to name. */}
          {vendor && vendor.name ? (
            <p className="cat-access__vendor">
              <span className="cat-access__vendor-k">Published by</span>{" "}
              {vendor.url ? (
                <a href={vendor.url} target="_blank" rel="noreferrer noopener">
                  {vendor.name}
                </a>
              ) : (
                <span className="cat-access__vendor-v">{vendor.name}</span>
              )}
            </p>
          ) : null}
        </aside>
      </div>

      {/* Generated media, said out loud, ABOVE the totals rather than under
          them. A buyer who works out on their own that the frames are test
          patterns stops reading; one who is told first can still evaluate the
          delivery format, which is what a fixture drop is for. It sits above
          the figures because it changes what every one of them means.
          `provenance_class` is set by the ingest from each take's own
          declaration, so this cannot be forgotten. */}
      {generated ? (
        <p className="cat-notice cat-notice--warn" role="note">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            {provenance === "synthetic"
              ? "Every clip in this collection is SYNTHETIC: the video, tactile and inertial streams were generated for catalog development and are not recordings of a real workspace. The schema, the QA record and the delivery format are real; the content is not."
              : "This collection MIXES recorded and synthetic clips. Check each clip's provenance before drawing any conclusion from its content; the per-clip record states which it is."}
          </span>
        </p>
      ) : null}

      {/* A <dl>, not a row of divs: each tile is a label/value pair and screen
          readers should read it as one. */}
      <dl className="cat-stats">
        {stats.map((s) => (
          <div className="cat-stat" key={s.label} title={s.hint}>
            <dt className="cat-label">{s.label}</dt>
            <Figure className="cat-stat-value cat-figure" text={s.value} />
            {s.sub ? <dd className="cat-stat-sub">{s.sub}</dd> : null}
          </div>
        ))}
      </dl>

      <div className="cat-masthead__meta">
        <dl className="cat-substats">
          {secondary.map((s) => (
            <div className="cat-substat" key={s.label} title={s.hint}>
              <dt>{s.label}</dt>
              <dd className="cat-figure">{s.value}</dd>
            </div>
          ))}
        </dl>

        {/* H10. A split published in the data is the only thing that makes two
            buyers' numbers comparable, so it is stated on the page, with the scope
            of the normalisation constants next to it. */}
        {splits && Array.isArray(splits.buckets) && splits.buckets.length ? (
          <p className="cat-masthead__line">
            <b>Splits</b>{" "}
            {splits.buckets.map((b, i) => (
              <span key={b.value}>
                {i ? " · " : ""}
                {b.label} {formatCount(b.clips)}
              </span>
            ))}
            {splits.normalization ? (
              <span title={splits.normalization.statement}>
                {" · normalisation fitted on "}
                {splits.normalization.scope}
              </span>
            ) : null}
          </p>
        ) : null}
      </div>

      {/* Two notices, two lines, neither truncating the other. `collection.notice`
          is the producer's standing caveat about the DATA and is passed through
          byte for byte at every access level; `access.notice` is about this
          ACCOUNT's access level. They used to be concatenated under a 300-char
          cap, which silently deleted the first for exactly the role that needed
          it most. */}
      {(collection && collection.notice) || (access && access.notice) ? (
        <div className="cat-notices">
          {collection && collection.notice ? (
            <p className="cat-notice" role="note">
              <Info size={15} aria-hidden="true" />
              <span>{dash(collection.notice)}</span>
            </p>
          ) : null}
          {access && access.notice ? (
            <p className="cat-notice cat-notice--access" role="note">
              <Info size={15} aria-hidden="true" />
              <span>{access.notice}</span>
            </p>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}

/**
 * A figure and its unit, in one element that cannot break between them.
 *
 * The unit is split off so it can be typeset differently — the numeral sits at
 * display size in a light weight and the unit at 40% of it in medium, which is
 * what stops "227.2 MB" reading as one long word. The split is on the LAST
 * space, and only when what precedes it contains a digit, so "1,234" and "—"
 * both pass through whole.
 */
function Figure({ text, className }) {
  const { head, unit } = splitFigure(text);
  return (
    <dd className={className}>
      {head}
      {unit ? <span className="cat-figure__unit">{unit}</span> : null}
    </dd>
  );
}

function splitFigure(text) {
  if (typeof text !== "string") return { head: dash(null), unit: null };
  const at = text.lastIndexOf(" ");
  if (at > 0 && /\d/.test(text.slice(0, at))) {
    return { head: text.slice(0, at), unit: text.slice(at + 1) };
  }
  return { head: text, unit: null };
}

/**
 * The line the header promotes, READ rather than derived.
 *
 * There used to be a slicer here: take sentence 1 unconditionally, then sentence
 * 2 if the pair fits 260 characters. It is deleted, and the reason is worth
 * keeping because the instinct to re-add it is strong.
 *
 * A slicer selects by POSITION, and position is not correlated with importance —
 * it is correlated with the order the writer felt like writing in, which for a
 * product paragraph is always claim first and limit last. Measured on the
 * shipped description the rule was not even a heuristic, it was deterministic:
 * sentence 1 was 172 characters and sentence 2 was 281, so the pair could never
 * fit and the buyer was shown exactly one sentence — the only one in the whole
 * paragraph with no qualification in it. "It is a capability sample and not a
 * corpus" and "no calibration into force units" were guaranteed to be one click
 * away, on a page whose entire job is to be trusted.
 *
 * So the promoted line is its own authored field, held to the same build rules
 * as the paragraph (validate.py scans `standfirst` for frame-level sync claims,
 * for the readout-grid size, and for "captured in" on a synthetic corpus), and
 * `collection.toml` states the authoring rule: one claim and one limit.
 *
 * The fallback is deliberately NOT the description. A collection that authored
 * no standfirst gets no promoted line and its whole paragraph in the disclosure,
 * because showing nothing is a visible gap someone fixes and showing an
 * unqualified first sentence is an invisible one nobody does.
 */
export function standfirst(collection) {
  const value = collection && collection.standfirst;
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Turn the one occurrence of `contact` inside `text` into the mailto link.
 *
 * String splitting, not dangerouslySetInnerHTML: `text` comes from the API and
 * `contact` from the manifest, and neither is ours to trust with markup.
 */
function linkifyContact(text, contact, href) {
  const at = text.indexOf(contact);
  if (at === -1) return text;
  return (
    <>
      {text.slice(0, at)}
      <a href={href}>{contact}</a>
      {text.slice(at + contact.length)}
    </>
  );
}

/** Minutes to one decimal with its unit, or an em-dash. */
function fmtMinutes(min) {
  if (typeof min !== "number" || !Number.isFinite(min)) return dash(null);
  return `${min < 10 ? min.toFixed(1) : Math.round(min)} min`;
}

/**
 * How many video frames the worst alignment error spans, at 30 fps.
 *
 * The frame rate is a per-clip field and the collection maximum is a
 * cross-clip figure, so there is no single true denominator here; 30 fps is
 * what every clip in this corpus records at and what the per-clip tab divides
 * by. Returns null rather than guessing when the figure is absent. The number
 * is only ever used in a hint sentence, never as a published figure.
 */
const NOMINAL_FPS = 30;

function framesFor(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return null;
  const frames = Math.ceil(ms / (1000 / NOMINAL_FPS));
  return frames > 1 ? frames : null;
}

/** Milliseconds to a fixed 2 dp with its unit, or an em-dash. Never rounded to 0. */
function formatMs(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return dash(null);
  return `${ms.toFixed(2)} ms`;
}

/**
 * The CTA's destination: a prefilled mail to the vendor's monitored role address.
 *
 * The collection id and version go in the subject because the first thing the
 * person answering has to work out otherwise is which drop the sender is looking
 * at. Everything is encoded; a collection name with an ampersand in it must not
 * truncate the body.
 */
function mailtoFor(contact, collection) {
  const id = (collection && collection.id) || "catalog";
  const version = collection && collection.version ? ` v${collection.version}` : "";
  const name = (collection && collection.name) || id;
  const subject = `Data access request — ${name}${version}`;
  const body = [
    `Collection: ${id}${version}`,
    "",
    "What we would like access to (clips, modalities, licence terms):",
    "",
    "",
    "Team and intended use:",
    "",
  ].join("\n");
  return (
    `mailto:${encodeURIComponent(contact)}` +
    `?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  );
}
