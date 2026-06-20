import { TargetReveal } from "./TargetReveal.jsx";

/**
 * Right-side copy that swaps with scroll beats. Each blurb has a data-index
 * and is visible only when --active-blurb matches. Selection is done via a
 * chain of CSS rules (see scroll-hero.css) to keep this render-free.
 *
 * Five blurbs map 1:1 with the five hand poses in narrative order:
 * pointy, +middle, +ring, +pinky, open palm.
 *
 * Each blurb has 1–2 target words (highlighted in lime via TargetReveal,
 * which slides a vertical line across the word and fades letters in
 * sequentially). Within a blurb, targets play strictly in `order` sequence.
 */
export function HeroBlurbs() {
  return (
    <div className="hero-blurbs" aria-live="polite">
      <p className="hero-blurb" data-index="0">
        A robot can recognize a{" "}
        <TargetReveal text="strawberry" blurbIndex={0} order={0} />. But can it pick one without{" "}
        <TargetReveal text="crushing it?" blurbIndex={0} order={1} />
      </p>
      <p className="hero-blurb" data-index="1">
        Recognition tells you <TargetReveal text="what" blurbIndex={1} order={0} /> to pick. Pressure tells you{" "}
        <TargetReveal text="how much" blurbIndex={1} order={1} /> to grip.
      </p>
      <p className="hero-blurb" data-index="2">
        <TargetReveal text="Force" blurbIndex={2} order={0} /> is the{" "}
        <TargetReveal text="invisible" blurbIndex={2} order={1} /> variable vision can't capture.
      </p>
      <p className="hero-blurb" data-index="3">
        We train <TargetReveal text="force" blurbIndex={3} order={0} /> from touch, not{" "}
        <TargetReveal text="guessing" blurbIndex={3} order={1} />.
      </p>
      <p className="hero-blurb" data-index="4">
        Robots that feel <TargetReveal text="pressure" blurbIndex={4} order={0} /> master{" "}
        <TargetReveal text="precision" blurbIndex={4} order={1} color="#cd5a3c" />.
      </p>
    </div>
  );
}
