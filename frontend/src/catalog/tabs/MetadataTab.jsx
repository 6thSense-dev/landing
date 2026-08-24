/**
 * MetadataTab — the reference layout, plus the three blocks buyers actually ask for.
 * ---------------------------------------------------------------------------
 * Props: { clip }
 *
 * Top half is a definition grid that goes 3 / 2 / 1 column by width, with
 * `.cat-label` field names and a hairline under every row (CAPTURE / CATEGORY /
 * DURATION / RESOLUTION / FRAME RATE / COUNTRY), DESCRIPTION full width, then
 * PACKAGE CONTENTS with a right-aligned file count and a list of monospace
 * filenames.
 *
 * Typographic rule, applied throughout and shared with the other tabs: the
 * `mono` prop on <Def> means "this is a MACHINE STRING a human may need to copy
 * character-for-character" — a take id, a device id, a checksum, a sign
 * convention. It does NOT mean "this is a number". Measurements are Pretendard
 * with tabular figures, which is what makes a column of them line up on the
 * decimal without the typewriter texture.
 *
 * Below that: DOCUMENTATION, QUALITY (H4), RIGHTS (H5), PRIVACY (H6),
 * PROVENANCE and KNOWN LIMITATIONS. We ship our caveats inside the product
 * rather than in a footnote, because the thing that disqualifies most corpora
 * for a commercial buyer is the licence, not the content.
 *
 * Three of those blocks exist because the data was already on the wire and
 * nothing rendered it:
 *
 *  - QUALITY (./QaBlock.jsx). `qa.checks[]` is the H4 table — check_id,
 *    category, result, measured_value, threshold, per clip — and the UI used to
 *    show a bare "Grade C" whose rule was nowhere on the page.
 *  - DOCUMENTATION. `media.docs.*` is deliberately signed for preview accounts
 *    (catalog_redact.py) and was linked from nowhere, so the decision had no
 *    effect. The DATASHEET is the most honest document in the bundle.
 *  - The full redaction sub-object. H6 asks for the human review RECORD — what
 *    was searched for, under which policy, by whom, when — and the renderer was
 *    collapsing all of it to "Blur · policy v1.2".
 *
 * Rendering rule from the contract, applied everywhere here: `null` means the
 * ingest could not determine the value, and is drawn as an em-dash. It is never
 * drawn as 0, never as "No", never as an empty cell.
 */

import { useMemo, useState } from "react";
import { Ban, Check, CircleDashed, Copy, Download, ExternalLink } from "lucide-react";

import { formatBytes, formatCount, formatDuration, dash } from "../format.js";
/* Country is stored as an alpha-2 join key; the DISPLAY name lives in the
   manifest's facets.country[].label, which is where the card and the filter
   bar get theirs. See useCatalog.facetLabel(). */
import { facetLabel } from "../useCatalog.js";
import { Block, Def, DocLink, href, humanise, yesNo } from "./parts.jsx";
import QaBlock from "./QaBlock.jsx";

const PERMISSIONS = [
  ["model_training", "Model training", "May the buyer train or fine-tune on this clip?"],
  ["commercial_use", "Commercial use", "May the resulting work ship in a product?"],
  ["redistribution", "Redistribution", "May the raw clip go to a third party?"],
  ["derived_model", "Derived model", "May weights influenced by this clip be released or sold?"],
];

/**
 * A permission is a legal fact, so colour is never the only thing that carries
 * it. Each state gets a word, a distinct glyph and a distinct border treatment
 * (solid / heavy / dashed, in parts.detail.css); the tint is the fourth cue,
 * not the first. Strip the colour and all three are still told apart.
 */
const PERMISSION_STATE = {
  granted: { label: "Granted", Icon: Check },
  denied: { label: "Denied", Icon: Ban },
  on_request: { label: "On request", Icon: CircleDashed },
};

/**
 * The per-clip documentation, in the order a buyer's acceptance pipeline reads
 * it. All five are signed for preview accounts; the datasheet is the one that
 * names the uncomfortable figures, which is exactly why it is first.
 */
const DOCS = [
  ["datasheet", "DATASHEET.md", "measured figures, gaps and caveats for this take"],
  ["readme", "README.md", "what is in the package and how to load it"],
  ["license", "LICENSE.txt", "the licence text this clip ships under"],
  ["sync_protocol", "SYNC_PROTOCOL.md", "how the streams were put on one clock"],
  ["checksums", "checksums.sha256", "digest per file, to verify the download"],
];

export default function MetadataTab({ clip }) {
  const [copied, setCopied] = useState(false);

  const files = useMemo(
    () => (Array.isArray(clip?.package_contents) ? clip.package_contents : []),
    [clip]
  );
  const filesBytes = useMemo(
    () => files.reduce((sum, f) => sum + (Number.isFinite(f.bytes) ? f.bytes : 0), 0),
    [files]
  );

  const copyJson = async () => {
    const text = JSON.stringify(clip, null, 2);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* clipboard is unavailable; the button simply does not confirm */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const qa = clip?.qa ?? null;

  const rights = clip?.rights ?? null;
  const privacy = clip?.privacy ?? null;
  const prov = clip?.provenance ?? null;
  const limits = Array.isArray(clip?.known_limitations) ? clip.known_limitations : [];
  const licenceHref = href(rights?.license_url);
  const archive = clip?.media?.archive ?? null;
  const archiveHref = href(archive?.url);
  const docs = clip?.media?.docs ?? null;
  const redaction = privacy?.redaction ?? null;
  const recordHref = href(redaction?.record_url);

  return (
    <section className="cat-m">
      <div className="cat-m-topbar">
        <button type="button" className="cat-btn" onClick={copyJson}>
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          <span>{copied ? "Copied" : "Copy JSON"}</span>
        </button>
        <span className="cat-sr" role="status" aria-live="polite">
          {copied ? "Clip record copied to the clipboard" : ""}
        </span>
      </div>

      {/* ---------------- the reference definition grid ---------------- */}
      <dl className="cat-m-defs">
        <Def label="Capture" value={humanise(clip?.capture)} />
        <Def
          label="Category"
          value={
            clip?.subcategory
              ? `${humanise(clip.category)} / ${humanise(clip.subcategory)}`
              : humanise(clip?.category)
          }
        />
        <Def
          label="Duration"
          value={clip?.duration_s != null ? formatDuration(clip.duration_s) : null}
        />
        <Def
          label="Resolution"
          value={
            Array.isArray(clip?.resolution)
              ? `${clip.resolution[0]} × ${clip.resolution[1]}`
              : null
          }
        />
        <Def label="Frame rate" value={clip?.fps != null ? `${clip.fps} fps` : null} />
        <Def label="Country" value={clip?.country ? facetLabel("country", clip.country) : null} />
        <Def label="Recorded" value={clip?.recorded_month} />
        <Def label="Subjects" value={clip?.subjects != null ? formatCount(clip.subjects) : null} />
        <Def label="Package size" value={clip?.bytes != null ? formatBytes(clip.bytes) : null} />
        <Def
          label="Modalities"
          value={clip?.modalities?.length ? clip.modalities.join(", ") : dash(null)}
        />
        <Def
          label="Hands"
          value={clip?.hands?.length ? clip.hands.join(" + ") : "none instrumented"}
        />
        <Def
          label="QA grade"
          value={
            qa?.grade
              ? `Grade ${qa.grade}${qa.disposition ? ` · ${humanise(qa.disposition)}` : ""}`
              : null
          }
          title="The letter is computed by the published rule; the word is the H4 disposition. Only 'accepted' clips are in this catalog, so read the warn count in Quality, not the word."
        />
        {/* H10: which published partition this clip belongs to. null is a real
            answer and renders as an em-dash — a buyer must then assume nothing. */}
        <Def label="Split" value={clip?.split ? humanise(clip.split) : null} />
        {/* "Channel yield", the same NAME the card and the header tile use for the
            same QUANTITY. It read "Usable channels" here, "Usable tactile" on the
            card (the identical percentage) and "Usable tactile" on the header (a
            channel-weighted DURATION) — one label over two quantities across three
            surfaces. The per-hand counts this used to be confused with keep the
            name "Usable channels", in the Quality block, where they are literally
            a count of channels. */}
        <Def
          label="Channel yield"
          value={
            clip?.qa?.tactile_coverage != null
              ? `${Math.round(clip.qa.tactile_coverage * 1000) / 10}% of readout sites (worst hand)`
              : null
          }
          title="Live-and-stable channels on the worst instrumented hand, over that hand's readout sites. Quote this census, never the readout-grid size."
        />
      </dl>

      {/* ---------------- the whole package, as one file ---------------- */}
      {archive && archiveHref ? (
        <Block title="Download" aside={archive.format || null}>
          <p className="cat-m-para">
            <a className="cat-btn" href={archiveHref} download>
              <Download size={14} aria-hidden="true" />
              <span>
                {clip.id}.{archive.format} ({formatBytes(archive.bytes)})
              </span>
            </a>
          </p>
          {archive.sha256 ? (
            <p className="cat-m-para cat-m-para--muted">
              <span className="cat-label">sha256</span>{" "}
              <span className="cat-mono cat-mono--wrap">{archive.sha256}</span> — verify this
              before you open anything.
            </p>
          ) : null}
        </Block>
      ) : null}

      {/* ---------------- documentation ---------------- */}
      {/* Signed for preview accounts on purpose (catalog_redact.py) and, until
          now, linked from nowhere — so the decision had no effect and the
          buyer's acceptance pipeline, which reads the datasheet first, had
          nothing to read. */}
      {docs && Object.values(docs).some(Boolean) ? (
        <Block title="Documentation" aside="per clip">
          <ul className="cat-m-docs">
            {DOCS.map(([key, label, why]) =>
              docs[key] ? (
                <li key={key}>
                  <DocLink url={docs[key]}>{label}</DocLink>
                  <span className="cat-m-docmeta">{why}</span>
                </li>
              ) : null,
            )}
          </ul>
        </Block>
      ) : null}

      {/* ---------------- description ---------------- */}
      <Block title="Description">
        {clip?.description ? (
          String(clip.description)
            .split(/\n{2,}/)
            .map((para, i) => (
              <p key={i} className="cat-m-para">
                {para.trim()}
              </p>
            ))
        ) : clip?.description_short ? (
          <p className="cat-m-para">{clip.description_short}</p>
        ) : (
          <p className="cat-m-para cat-m-para--dash">{dash(null)}</p>
        )}
      </Block>

      {/* ---------------- package contents ---------------- */}
      <Block
        title="Package contents"
        aside={
          files.length
            ? `${formatCount(files.length)} file${files.length === 1 ? "" : "s"}${
                filesBytes ? ` · ${formatBytes(filesBytes)}` : ""
              }`
            : null
        }
      >
        {files.length ? (
          <ul className="cat-m-files">
            {files.map((f, i) => {
              const url = href(f.url);
              return (
                <li key={`${f.path}-${i}`}>
                  <span className="cat-m-file">
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer noopener">
                        {f.path}
                      </a>
                    ) : (
                      f.path
                    )}
                  </span>
                  <span className="cat-m-filemeta">
                    {f.bytes != null ? formatBytes(f.bytes) : dash(null)}
                    {f.role ? ` · ${f.role}` : ""}
                    {f.sha256 ? "" : " · no digest"}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="cat-m-para cat-m-para--dash">
            The package has not been assembled, so there is no file manifest to check integrity
            against.
          </p>
        )}
      </Block>

      {/* ---------------- quality (H4) ---------------- */}
      <QaBlock qa={qa} />

      {/* ---------------- rights (H5) ---------------- */}
      <Block
        title="Rights"
        aside={
          rights?.determined_utc
            ? `reviewed ${String(rights.determined_utc).slice(0, 10)}`
            : "never reviewed"
        }
      >
        {rights ? (
          <>
            <ul className="cat-m-perms">
              {PERMISSIONS.map(([key, label, why]) => {
                const v = rights[key];
                const state = PERMISSION_STATE[v] ?? null;
                const Icon = state?.Icon ?? null;
                return (
                  <li key={key}>
                    <span className="cat-label">{label}</span>
                    <span className={`cat-perm cat-perm--${v}`}>
                      {Icon ? <Icon size={12} aria-hidden="true" /> : null}
                      <span>{state ? state.label : dash(null)}</span>
                    </span>
                    <span className="cat-m-why">{why}</span>
                  </li>
                );
              })}
            </ul>
            <dl className="cat-m-defs cat-m-defs--tight">
              <Def label="Licence" value={rights.license_name || rights.license_id} />
              <Def label="Holder" value={rights.holder} />
              <Def label="Attribution" value={yesNo(rights.attribution_required)} />
            </dl>
            {licenceHref ? (
              <p className="cat-m-para">
                <a
                  className="cat-m-link"
                  href={licenceHref}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Read the licence
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              </p>
            ) : null}
            {Array.isArray(rights.restrictions) && rights.restrictions.length ? (
              <ul className="cat-m-list">
                {rights.restrictions.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : (
              <p className="cat-m-para cat-m-para--muted">
                No restrictions beyond the licence.
              </p>
            )}
            {rights.notes ? <p className="cat-m-para">{rights.notes}</p> : null}
            <p className="cat-note">
              These four permissions are per-clip and independent, and they override anything the
              collection-level licence says. There is no “unknown”: an unreviewed clip reads{" "}
              <strong>denied</strong>.
            </p>
          </>
        ) : (
          <p className="cat-m-para cat-m-para--dash">{dash(null)}</p>
        )}
      </Block>

      {/* ---------------- privacy (H6) ---------------- */}
      <Block title="Privacy">
        {privacy ? (
          <>
            <dl className="cat-m-defs cat-m-defs--tight">
              <Def label="Consent on file" value={yesNo(privacy.consent_on_file)} />
              <Def label="Faces redacted" value={yesNo(privacy.faces_redacted)} />
              <Def
                label="PII review"
                value={privacy.pii_review ? humanise(privacy.pii_review) : null}
              />
              <Def label="Notice given" value={yesNo(privacy.notice_given)} />
              <Def
                label="Identifiable persons"
                value={
                  privacy.identifiable_persons != null
                    ? formatCount(privacy.identifiable_persons)
                    : null
                }
              />
              <Def
                label="Identifiable premises"
                value={yesNo(privacy.identifiable_premises)}
              />
              <Def
                label="Retention"
                value={
                  privacy.retention
                    ? privacy.retention.delete_after_utc
                      ? `until ${String(privacy.retention.delete_after_utc).slice(0, 10)}`
                      : "open ended"
                    : null
                }
              />
              <Def
                label="Re-identification"
                value={privacy.reidentification_prohibited ? "Prohibited" : dash(null)}
              />
            </dl>
            {/* H6 asks for the review RECORD, not its outcome: what was searched
                for, under which policy version, by whom and when. This used to
                collapse to one line ("Blur · policy v1.2") and drop the other
                four fields — which are precisely the four counsel asks for. */}
            <div className="cat-m-sub">
              <p className="cat-label">Redaction record</p>
              {redaction ? (
                <>
                  <dl className="cat-m-defs cat-m-defs--tight">
                    <Def label="Method" value={humanise(redaction.method)} />
                    <Def label="Policy version" value={redaction.policy_version} mono />
                    <Def label="Reviewer" value={redaction.reviewer} mono />
                    <Def
                      label="Reviewed"
                      value={
                        redaction.reviewed_utc
                          ? String(redaction.reviewed_utc).replace("T", " ").replace("Z", " UTC")
                          : null
                      }
                      mono
                    />
                    <Def
                      label="Items redacted"
                      value={
                        redaction.items_redacted != null
                          ? formatCount(redaction.items_redacted)
                          : null
                      }
                    />
                    <Def
                      label="Full record"
                      value={
                        recordHref ? (
                          <a
                            className="cat-m-link"
                            href={recordHref}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            Open
                            <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        ) : null
                      }
                    />
                  </dl>
                  {Array.isArray(redaction.targets) && redaction.targets.length ? (
                    <>
                      <p className="cat-label cat-m-subhead">Targets searched for</p>
                      <ul className="cat-m-chips">
                        {redaction.targets.map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p className="cat-m-para cat-m-para--dash">
                      No redaction targets are listed, so there is no statement of what was
                      looked for — which is not the same as nothing having been found.
                    </p>
                  )}
                </>
              ) : (
                <p className="cat-m-para cat-m-para--dash">
                  No redaction record ships with this clip.
                </p>
              )}
            </div>

            {privacy.retention?.policy ? (
              <p className="cat-m-para">{privacy.retention.policy}</p>
            ) : null}
            {privacy.notes ? <p className="cat-m-para">{privacy.notes}</p> : null}
            <p className="cat-note">
              An em-dash here means no assessment was made, which counsel reads as worse than a
              “No”. It is never a substitute for a determined answer.
            </p>
          </>
        ) : (
          <p className="cat-m-para cat-m-para--dash">{dash(null)}</p>
        )}
      </Block>

      {/* ---------------- provenance ---------------- */}
      <Block title="Provenance">
        {prov ? (
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def label="Take id" value={prov.take_id} mono />
            {/* The per-clip half of the collection's provenance banner. A buyer
                who filters or forwards a single clip must be able to see it
                here, not only on the header they scrolled past. */}
            <Def
              label="Media"
              value={
                prov.media_class === "synthetic"
                  ? "Synthetic — generated, not recorded"
                  : prov.media_class === "recorded"
                    ? "Recorded on hardware"
                    : null
              }
            />
            <Def label="Device" value={prov.device_id} mono />
            <Def label="Firmware" value={prov.firmware} mono />
            <Def label="Operator" value={prov.operator} mono />
            <Def label="Recorded" value={prov.recorded_local} mono />
            <Def label="Packaged" value={prov.packaged_utc} mono />
            <Def label="Pipeline" value={prov.pipeline_version} mono />
            <Def label="Session" value={prov.session_id} mono />
            <Def label="Environment" value={prov.environment} />
          </dl>
        ) : (
          <p className="cat-m-para cat-m-para--dash">{dash(null)}</p>
        )}
        {prov?.note ? <p className="cat-m-para">{prov.note}</p> : null}
      </Block>

      {/* ---------------- known limitations ---------------- */}
      <Block title="Known limitations" aside={limits.length ? formatCount(limits.length) : null}>
        {limits.length ? (
          <ul className="cat-m-list">
            {limits.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        ) : (
          <p className="cat-m-para cat-m-para--muted">
            The record claims none. An empty list is an affirmative claim, and it is almost never
            true — if a limitation has not been looked for, that absence is itself one.
          </p>
        )}
      </Block>
    </section>
  );
}

/* Def, Block, DocLink, humanise, yesNo and href now live in ./parts.jsx —
   the Calibration & sync tab renders the same shapes, and two copies of a
   renderer whose one job is to apply the em-dash rule consistently is how the
   rule stops being applied consistently. The H4 check table is ./QaBlock.jsx for
   the same reason plus one more: it is the single most scrutinised thing on the
   page and deserves to be readable on its own. */


