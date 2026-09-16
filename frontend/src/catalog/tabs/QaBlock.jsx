/**
 * QaBlock — the H4 record: one disposition, and every check with its threshold.
 * ---------------------------------------------------------------------------
 * Props: { qa }   (the clip record's `qa` object, or null)
 *
 * H4 asks for exactly one disposition per clip and, for every check, both the
 * measured value AND the bound it was measured against. This record has all of
 * that, verbatim — `sync_max_skew_ms warn 34.078 vs 33.0`,
 * `calibration_rectification_residual_px pass 0.314 vs 0.5` — and the UI used to
 * show a single letter, "Grade C", whose rule appears nowhere on the page.
 *
 * The table below is the most credible artefact in the product: it is the thing a
 * buyer's acceptance pipeline can ingest directly rather than take on trust. Two
 * rules govern how it renders:
 *
 *  - The disposition is never shown alone. Every published clip is `accepted` — a
 *    fail quarantines it upstream — so the word carries no information; the warn
 *    count does. "Accepted with 3 warns" is the honest headline.
 *  - Rows sort worst-first inside their category, so a fail or a warn cannot be
 *    buried under fifteen passes.
 *  - Checks whose answer is a property of the PROGRAMME rather than of this take are
 *    separated out and collapsed. Seven of the nine warns on a typical clip warn
 *    identically on every clip -- nobody has annotated any clip, no clip has a clap
 *    decoded, the rig has one cam-IMU solve or none. Repeating them on each clip page
 *    reads as a corpus riddled with problems when only one to three warns are actually
 *    about THIS clip. Nothing is hidden: they are still rendered, in full, one <details>
 *    away, and the record a buyer downloads is unchanged.
 */

import { AlertTriangle } from "lucide-react";

import { formatCount, dash } from "../format.js";
import { Block, Def, humanise, yesNo } from "./parts.jsx";

/** A measured value or a threshold, printed the way the record stored it. */
export function checkValue(v) {
  if (v == null) return dash(null);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    // Round only what needs it: 0.9999 and 33.0 must both survive intact.
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 1e6) / 1e6);
  }
  return String(v);
}

/** Worst first. A warn buried under fifteen passes is a warn nobody reads.
 *
 * `not_applicable` sorts LAST, below `pass`. It is not a lesser pass and it is not a
 * softer `not_run`: it means the package does not carry the stream this check tests, so
 * there was never anything to measure. Those rows are the least newsworthy thing in the
 * table — for a camera-only clip they are simply the shape of the product — and putting
 * them above `pass` would make a clean camera-only clip's check table open on three rows
 * that say nothing happened. */
const RESULT_ORDER = { fail: 0, warn: 1, not_run: 2, pass: 3, not_applicable: 4 };

/** `qa.checks` grouped by category, worst result first inside each group. */
export function groupChecks(checks) {
  const by = new Map();
  for (const c of checks) {
    const key = c.category || "other";
    if (!by.has(key)) by.set(key, []);
    by.get(key).push(c);
  }
  for (const rows of by.values()) {
    rows.sort(
      (a, b) =>
        (RESULT_ORDER[a.result] ?? 9) - (RESULT_ORDER[b.result] ?? 9) ||
        String(a.check_id).localeCompare(String(b.check_id)),
    );
  }
  return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

/** Split into what is about THIS clip and what is about the whole collection.
 *  A check with no `scope` predates the field and is treated as clip-specific, which is
 *  the conservative reading -- an old record keeps showing everything it always did. */
export function splitByScope(checks) {
  const clip = [];
  const collection = [];
  for (const c of checks) (c.scope === "collection" ? collection : clip).push(c);
  return { clip, collection };
}

/** How many checks landed on each result. */
export function tallyChecks(checks) {
  const t = { pass: 0, warn: 0, fail: 0, not_run: 0, not_applicable: 0 };
  for (const c of checks) if (c.result in t) t[c.result] += 1;
  return t;
}

export default function QaBlock({ qa }) {
  const checks = Array.isArray(qa?.checks) ? qa.checks : [];
  const { clip: clipChecks, collection: colChecks } = splitByScope(checks);
  const checkGroups = groupChecks(clipChecks);
  const tally = tallyChecks(clipChecks);
  const colTally = tallyChecks(colChecks);
  const colGroups = groupChecks(colChecks);

  return (
    <Block
      title="Quality"
      aside={
        checks.length
          ? `${formatCount(clipChecks.length)} clip checks · ${tally.pass} pass · ` +
            `${tally.warn} warn` +
            (tally.fail ? ` · ${tally.fail} fail` : "") +
            (tally.not_run ? ` · ${tally.not_run} not run` : "") +
            /* Counted separately from `not run`, and worded as the product fact it is.
               Folding the two together is what let three tactile rows on a camera-only
               clip read as three checks somebody forgot to run. */
            (tally.not_applicable ? ` · ${tally.not_applicable} n/a` : "") +
            (colChecks.length ? ` · +${colChecks.length} collection-wide` : "")
          : null
      }
    >
      {qa ? (
        <>
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def label="Disposition" value={humanise(qa.disposition)} />
            <Def label="Grade" value={qa.grade ? `Grade ${qa.grade}` : null} />
            <Def
              label="Frames dropped"
              value={
                qa.video_frames_dropped != null
                  ? formatCount(qa.video_frames_dropped) +
                    (qa.video_frames_delivered
                      ? ` of ${formatCount(qa.video_frames_delivered)}`
                      : "")
                  : null
              }
            />
            <Def
              label="Tactile CRC"
              value={
                qa.tactile_crc_pass_rate != null
                  ? `${(qa.tactile_crc_pass_rate * 100).toFixed(2)}%`
                  : null
              }
            />
            <Def
              label="Usable channels"
              value={
                qa.usable_channels
                  ? ["left", "right"]
                      .filter((h) => qa.usable_channels[h] != null)
                      .map((h) => `${h} ${formatCount(qa.usable_channels[h])}`)
                      .join(" · ") || null
                  : null
              }
            />
            <Def label="Checksums verified" value={yesNo(qa.checksums_verified)} />
          </dl>

          {tally.warn || tally.fail ? (
            <p className="cat-note cat-note--warn">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                This clip is dispositioned <strong>{qa.disposition ?? "—"}</strong> with{" "}
                {formatCount(tally.warn)} warn{tally.warn === 1 ? "" : "s"}
                {tally.fail ? ` and ${formatCount(tally.fail)} fail` : ""} of its own. Every
                one is a measured value outside its preferred bound, listed below with the
                bound it missed. Accepted does not mean clean.
                {colTally.warn || colTally.fail
                  ? ` A further ${formatCount(colTally.warn + colTally.fail)} apply to every
                     clip in this collection rather than to this one; they are listed below
                     the table.`
                  : ""}
              </span>
            </p>
          ) : null}

          {checkGroups.length ? (
            <div className="cat-tablewrap">
              <table className="cat-table">
                <caption className="cat-sr">
                  Every QA check for this clip: identifier, result, measured value and the
                  threshold it was measured against, grouped by category.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Check</th>
                    <th scope="col">Result</th>
                    <th scope="col">Measured</th>
                    <th scope="col">Threshold</th>
                    <th scope="col">Units</th>
                  </tr>
                </thead>
                {checkGroups.map(([category, rows]) => (
                  <tbody key={category}>
                    <tr>
                      <th scope="colgroup" colSpan={5} className="cat-qa-cat">
                        {humanise(category)}
                      </th>
                    </tr>
                    {rows.map((c) => (
                      <tr
                        key={c.check_id}
                        className={
                          c.result === "warn" || c.result === "fail"
                            ? "cat-table-row--warn"
                            : ""
                        }
                      >
                        <th scope="row" className="cat-mono">
                          {c.check_id}
                          {c.note ? <span className="cat-qa-note">{c.note}</span> : null}
                        </th>
                        <td>
                          <span className={`cat-qa-result cat-qa-result--${c.result}`}>
                            {String(c.result || "—").replace(/_/g, " ")}
                          </span>
                        </td>
                        {/* Left, not right: these columns hold `0.314` and
                            `kannala_brandt` in adjacent rows, and right-aligning
                            a mixed column lines up neither. */}
                        <td className="cat-qa-val">{checkValue(c.measured_value)}</td>
                        <td className="cat-qa-val">{checkValue(c.threshold)}</td>
                        <td className="cat-qa-val">{c.units ?? dash(null)}</td>
                      </tr>
                    ))}
                  </tbody>
                ))}
              </table>
            </div>
          ) : (
            <p className="cat-m-para cat-m-para--dash">
              This record carries no per-check table, so the grade above cannot be audited
              against the measurements that produced it.
            </p>
          )}
          {colGroups.length ? (
            <details className="cat-qa-collection">
              <summary>
                {formatCount(colChecks.length)} check
                {colChecks.length === 1 ? "" : "s"} that apply to the whole collection, not
                to this clip
                {colTally.warn || colTally.fail
                  ? ` — ${formatCount(colTally.warn + colTally.fail)} outside bound`
                  : ""}
              </summary>
              {/* Says only what the rows below it say. The earlier version asserted a
                  reason for the missing split — "one operator, one rig and one day" — which
                  this drop contradicts on rig, day and jurisdiction, and asserted it whether
                  or not the record actually omitted a split. A paragraph that argues with
                  the table beneath it costs more credibility than the amber it saves. */}
              <p className="cat-note">
                These miss their bound identically on every clip in the collection, so they
                describe the programme rather than this take. They are here in full rather
                than repeated on every clip page, and the record you download is unchanged.
              </p>
              <div className="cat-tablewrap">
                <table className="cat-table">
                  <caption className="cat-sr">
                    Collection-wide QA checks: identifier, result, measured value and
                    threshold, grouped by category.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Check</th>
                      <th scope="col">Result</th>
                      <th scope="col">Measured</th>
                      <th scope="col">Threshold</th>
                      <th scope="col">Units</th>
                    </tr>
                  </thead>
                  {colGroups.map(([category, rows]) => (
                    <tbody key={category}>
                      <tr>
                        <th scope="colgroup" colSpan={5} className="cat-qa-cat">
                          {humanise(category)}
                        </th>
                      </tr>
                      {rows.map((c) => (
                        <tr
                          key={c.check_id}
                          className={
                            (c.result === "warn" || c.result === "fail") &&
                            c.kind !== "by_design"
                              ? "cat-table-row--warn"
                              : ""
                          }
                        >
                          <th scope="row" className="cat-mono">
                            {c.check_id}
                            {/* Only a row that actually misses its bound can be excused
                                by design. Gated on the result too, because a `pass` wearing
                                a "by design" chip reads as a decision not to measure
                                something we did in fact measure. */}
                            {c.kind === "by_design" &&
                            (c.result === "warn" || c.result === "fail") ? (
                              <span className="cat-qa-bydesign">by design</span>
                            ) : null}
                            {c.note ? <span className="cat-qa-note">{c.note}</span> : null}
                          </th>
                          <td>
                            <span className={`cat-qa-result cat-qa-result--${c.result}`}>
                              {String(c.result || "—").replace(/_/g, " ")}
                            </span>
                          </td>
                          <td className="cat-qa-val">{checkValue(c.measured_value)}</td>
                          <td className="cat-qa-val">{checkValue(c.threshold)}</td>
                          <td className="cat-qa-val">{c.units ?? dash(null)}</td>
                        </tr>
                      ))}
                    </tbody>
                  ))}
                </table>
              </div>
            </details>
          ) : null}

          {qa.notes ? <p className="cat-m-para">{qa.notes}</p> : null}
          <p className="cat-note">
            Every row carries both its measurement and the bound it was judged against, which
            is what makes this table something an acceptance pipeline can ingest rather than a
            letter to take on trust. A <code className="cat-code">warn</code> is inside the
            acceptance bound and outside the preferred one; a{" "}
            <code className="cat-code">fail</code> quarantines the clip and it never reaches
            this catalog.
          </p>
          {tally.not_applicable || colTally.not_applicable ? (
            <p className="cat-note">
              <code className="cat-code">not applicable</code> is not a pass and not a shrug:
              this package does not carry the stream that check tests, so there was nothing to
              measure. It is the only result that does not cap the grade. A check that{" "}
              <em>does</em> apply here and was not run reads{" "}
              <code className="cat-code">not run</code> and still caps it. Each n/a row names
              the structural fact behind it, and you can verify that fact yourself in the same
              record — <code className="cat-code">hands</code> for the tactile checks,{" "}
              <code className="cat-code">sync</code> for the inter-stream ones.
            </p>
          ) : null}
        </>
      ) : (
        <p className="cat-m-para cat-m-para--dash">{dash(null)}</p>
      )}
    </Block>
  );
}
