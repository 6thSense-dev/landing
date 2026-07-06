import { Suspense, lazy } from "react";

// TEMPORARY capture page for the robotic hand. Route: /robo-shot.
// Tweak size/position LIVE via URL params (no waiting on a rebuild):
//   /robo-shot?scale=1.6&y=-0.3&rot=-0.06
// then drag to rotate and screenshot. We key the result into robo.webp.
const HandTurntable = lazy(() => import("../lib/HandTurntable.jsx"));

const num = (v, d) => (v != null && v !== "" && !Number.isNaN(parseFloat(v)) ? parseFloat(v) : d);

export default function RoboShot() {
  const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const scale = num(q.get("scale"), 1.3);
  const y = num(q.get("y"), -0.15);
  const rot = num(q.get("rot"), -0.06);

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#000", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <Suspense fallback={null}>
          <HandTurntable still hires scale={scale} posX={0} posY={y} rotY={rot} />
        </Suspense>
      </div>
      <div style={{ position: "fixed", bottom: 14, left: 0, right: 0, textAlign: "center",
        color: "#777", fontFamily: "ui-monospace, monospace", fontSize: 13 }}>
        scale={scale} · y={y} · rot={rot} &nbsp;—&nbsp; tweak in the URL (?scale=&y=&rot=), drag to rotate, then screenshot
      </div>
    </div>
  );
}
