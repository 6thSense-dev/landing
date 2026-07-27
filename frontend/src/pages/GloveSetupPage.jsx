import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import "./product.css";
import "./glove-setup.css";

/**
 * Glove setup & connection guide (/gloves/setup).
 *
 * UNLISTED by design: reached via a QR code shipped with the hardware, not
 * from the site nav. Deliberately absent from sitemap.xml, the SEO prerender
 * manifests (src/seo/pages.js), and every nav — and it injects a robots
 * noindex meta tag below so it stays out of search results. Keep it that way
 * when editing.
 *
 * Reuses the light-paper product-page layout (product.css), same as
 * LegalPage, so no new styling system is introduced.
 */

const steps = [
  {
    h2: "1. Unbox and inspect",
    body: "Remove the glove from its case and check the fabric and wiring harness for shipping damage. The sensor matrix is flexible but shouldn't be creased sharply — store the glove flat or on the provided form.",
  },
  {
    h2: "2. Connect over USB",
    body: "Plug the glove's USB cable into your capture machine. Use a direct port where possible — unpowered hubs are a common source of dropped frames. The glove enumerates as a serial device; no drivers are needed on Linux or macOS.",
  },
  {
    h2: "3. Install the SDK",
    body: [
      "The glove streams through the 6thSense Nerve SDK, a typed Python library with honest device/host timestamps on every frame.",
      "Install it in your environment, then confirm the glove is visible:",
    ],
    code: 'pip install "sixthsense[glove]"\n\npython -c "import sixthsense as ss; print(ss.devices())"',
  },
  {
    h2: "4. Verify the stream",
    body: [
      "Open the device and read a frame. Every sample carries the raw tactile grid plus both clocks (host receive time and, on V1 gloves, the device's own microsecond clock).",
    ],
    code:
      "import sixthsense as ss\n\ndev = ss.open()\ntry:\n    frame = dev.read()\n    print(frame.host_recv_ts, frame.device_ts_us, frame.seq)\nfinally:\n    dev.close()",
  },
  {
    h2: "5. Troubleshooting",
    items: [
      "Glove not listed by ss.devices() — reseat the USB cable, try another port, and check the cable isn't charge-only.",
      "Frames stop mid-session — the SDK auto-reconnects on USB glitches; a persistent DeviceDisconnected error usually means a loose connector at the cuff.",
      "No hardware yet? Run `sixthsense demo -n 20` to stream the built-in glove simulator and validate your pipeline end to end.",
    ],
  },
];

/** Clipboard write with a fallback for non-secure contexts (a phone hitting
 *  this guide over plain http has no navigator.clipboard). */
async function writeToClipboard(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  if (!ok) throw new Error("copy command rejected");
}

/**
 * A wrapping code block with a copy button.
 *
 * Both halves matter on a phone: the commands wrap (see .setup-pre) so nothing
 * is silently cut off, and copying does not require the near-impossible
 * text-selection drag inside a <pre> on a touch screen.
 */
function CodeBlock({ code, stepLabel }) {
  const [state, setState] = useState("idle"); // idle | copied | error
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = useCallback(async () => {
    clearTimeout(timer.current);
    try {
      await writeToClipboard(code);
      setState("copied");
    } catch {
      setState("error");
    }
    timer.current = setTimeout(() => setState("idle"), 2400);
  }, [code]);

  const labels = {
    idle: "Copy",
    copied: "Copied",
    error: "Select manually",
  };

  return (
    <div className="setup-codeblock">
      <div className="setup-codeblock-bar">
        <button
          type="button"
          className={
            "setup-copy" +
            (state === "copied" ? " setup-copy--copied" : "") +
            (state === "error" ? " setup-copy--error" : "")
          }
          onClick={copy}
          aria-label={`Copy the commands for ${stepLabel}`}
        >
          <CopyIcon copied={state === "copied"} />
          <span>{labels[state]}</span>
        </button>
      </div>
      {/* One block per source line so a wrapped line gets a hanging indent —
          without it, a continuation of `print(frame.host_recv_ts,` looks like
          a new statement at column 0 and invites a typo. */}
      <pre className="setup-pre">
        <code>
          {code.split("\n").map((line, i) => (
            <span className="setup-line" key={i}>
              {line}
            </span>
          ))}
        </code>
      </pre>
      {/* Announces the result to screen readers without stealing focus. */}
      <span className="setup-sr-only" role="status" aria-live="polite">
        {state === "copied"
          ? `Commands for ${stepLabel} copied to clipboard`
          : state === "error"
            ? "Copy failed — select the text manually"
            : ""}
      </span>
    </div>
  );
}

function CopyIcon({ copied }) {
  return (
    <svg
      className="setup-copy-icon"
      width="15"
      height="15"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {copied ? (
        <polyline points="2.5,8.5 6,12 13.5,4" />
      ) : (
        <>
          <rect x="5.5" y="5.5" width="8" height="9" rx="1.5" />
          <path d="M10.5 3.5v-1a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h1" />
        </>
      )}
    </svg>
  );
}

/** Renders `backticked` spans in the approved copy as real inline code. */
function withInlineCode(text) {
  return text.split(/`([^`]+)`/g).map((chunk, i) =>
    i % 2 === 1 ? <code key={i}>{chunk}</code> : chunk
  );
}

export default function GloveSetupPage() {
  useEffect(() => {
    const prevTitle = document.title;
    document.title = "Glove Setup & Connection | 6thSense";

    // Unlisted page: keep it out of search indexes even if the URL leaks.
    //
    // index.html ships a static `robots: index, follow`, so appending a second
    // tag would leave two conflicting directives on this page. Crawlers do
    // resolve that by taking the most restrictive, but this is the one page
    // whose entire purpose depends on staying unlisted, so we don't lean on
    // that rule: overwrite the existing tag and restore it on unmount, leaving
    // exactly one robots tag at all times.
    const existing = document.head.querySelector('meta[name="robots"]');
    const prevRobots = existing ? existing.content : null;
    const meta = existing || document.createElement("meta");
    if (!existing) {
      meta.name = "robots";
      document.head.appendChild(meta);
    }
    meta.content = "noindex, nofollow";

    return () => {
      document.title = prevTitle;
      // Put the document back exactly as we found it: restore the original
      // directive if there was one, otherwise remove the tag we added.
      if (prevRobots === null) meta.remove();
      else meta.content = prevRobots;
    };
  }, []);

  const paragraphs = (body) => (Array.isArray(body) ? body : [body]);

  return (
    <div className="product-page glove-setup">
      <header className="product-nav">
        <Link className="product-wordmark" to="/" aria-label="6thSense home">
          <img className="product-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
          <span>6THSENSE</span>
        </Link>
      </header>

      <main className="product-main">
        <article className="product-article">
          <p className="product-kicker">Hardware guide</p>
          <h1 className="product-h1">Glove setup &amp; connection</h1>
          <p className="product-intro">
            Get your 6thSense tactile glove connected and streaming in a few
            minutes. If anything here doesn't match what's in front of you,
            write us — this page evolves with the hardware.
          </p>

          {steps.map((s, i) => (
            <section className="product-section" key={i}>
              <h2 className="product-h2">{s.h2}</h2>
              {s.body &&
                paragraphs(s.body).map((p, k) => (
                  <p className="product-body" key={k}>
                    {p}
                  </p>
                ))}
              {s.code && <CodeBlock code={s.code} stepLabel={s.h2} />}
              {s.items && (
                <ul className="product-list">
                  {s.items.map((li, j) => (
                    <li key={j}>{withInlineCode(li)}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}

          <section className="product-section">
            <h2 className="product-h2">Need a hand?</h2>
            <p className="product-body">We answer setup questions directly:</p>
            <a className="setup-contact-link" href="mailto:ops@6thsense.dev">
              ops@6thsense.dev
            </a>
          </section>
        </article>
      </main>
    </div>
  );
}
