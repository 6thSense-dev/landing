import { useEffect } from "react";
import { Link } from "react-router-dom";

import "./product.css";

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

export default function GloveSetupPage() {
  useEffect(() => {
    const prevTitle = document.title;
    document.title = "Glove Setup & Connection | 6thSense";

    // Unlisted page: keep it out of search indexes even if the URL leaks.
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);

    return () => {
      document.title = prevTitle;
      meta.remove();
    };
  }, []);

  const paragraphs = (body) => (Array.isArray(body) ? body : [body]);

  return (
    <div className="product-page">
      <header className="product-nav">
        <Link className="product-wordmark" to="/" aria-label="6thSense home">
          {/* 118KB PNG for a 26x26 render; same mark at 128x128 (exact 1/8 of the
              source, aspect preserved), PNG kept as the fallback src. */}
          <img className="product-logo" src="/logos/Logo_Alpha.png"
            srcSet="/logos/Logo_Alpha-128.webp"
            alt="" aria-hidden="true" />
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
              {s.code && (
                <pre className="product-body" style={{ overflowX: "auto" }}>
                  <code>{s.code}</code>
                </pre>
              )}
              {s.items && (
                <ul className="product-list">
                  {s.items.map((li, j) => (
                    <li key={j}>{li}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}

          <section className="product-section">
            <h2 className="product-h2">Need a hand?</h2>
            <p className="product-body">
              We answer setup questions directly:{" "}
              <a className="product-related-link" href="mailto:ops@6thsense.dev">
                ops@6thsense.dev
              </a>
            </p>
          </section>
        </article>
      </main>
    </div>
  );
}
