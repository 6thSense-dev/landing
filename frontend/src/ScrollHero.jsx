import { HeroStageOne } from "./HeroStageOne.jsx";
import { HeroStageTwo } from "./HeroStageTwo.jsx";
import { QuoteTimeline } from "./QuoteTimeline.jsx";
import { TactileField } from "./TactileField.jsx";
import AuroraBg from "./lib/AuroraBg.jsx";

// Site-wide aurora is an OPT-IN PREVIEW until Ronak approves replacing the
// constellation everywhere. Default OFF: the homepage keeps the TactileField
// constellation exactly as-is. Turn on the preview with `?aurora` (or flip
// AURORA_SITEWIDE to true once approved). See tasks/products-v2-roadmap.md.
const AURORA_SITEWIDE = false;
function auroraPreviewOn() {
  if (AURORA_SITEWIDE) return true;
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("aurora");
}

/**
 * Three-block hero:
 *   [ HeroStageOne (sticky) ]   counting 1→5, assemble (dots + glove descend)
 *   [ QuoteTimeline (normal) ]  vertical timeline of 4 research citations
 *   [ HeroStageTwo (sticky) ]   pipeline, video preview, finale form
 *
 * A single TactileField mounts at the root with absolute positioning so the
 * shader-driven particle background renders continuously across all three
 * blocks. Brand-moment opener (sessionStorage-gated) lives in OpenerAnimation.
 */
export function ScrollHero() {
  const aurora = auroraPreviewOn();
  return (
    <div className="scroll-hero">
      {aurora ? <AuroraBg /> : <TactileField />}
      <HeroStageOne />
      <QuoteTimeline />
      <HeroStageTwo />
    </div>
  );
}
