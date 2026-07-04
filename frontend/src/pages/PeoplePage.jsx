import { Link } from "react-router-dom";

/**
 * Placeholder for the /people section (linked from the nav). Real content
 * comes later; this keeps the nav link from falling through to the homepage
 * catch-all. Dark, on-brand, minimal.
 */
export default function PeoplePage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#000",
        color: "#f4f1ea",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "14px",
        textAlign: "center",
        padding: "24px",
        fontFamily: '"General Sans", system-ui, sans-serif',
      }}
    >
      <div
        style={{
          fontFamily: '"Geist Mono", ui-monospace, monospace',
          fontSize: "12px",
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "#f0612a",
        }}
      >
        People
      </div>
      <h1 style={{ fontSize: "clamp(34px, 5vw, 58px)", fontWeight: 600, margin: 0 }}>
        Coming soon.
      </h1>
      <p style={{ color: "#a49c86", maxWidth: "42ch", fontSize: "17px", lineHeight: 1.6 }}>
        The people building 6thSense. This page is on the way.
      </p>
      <Link to="/" style={{ color: "#f0612a", textDecoration: "none", marginTop: "8px" }}>
        ← Back home
      </Link>
    </div>
  );
}
