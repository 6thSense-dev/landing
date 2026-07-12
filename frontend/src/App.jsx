import { useReducedMotion } from "framer-motion";
import { ScrollHero } from "./ScrollHero.jsx";
import { OpenerAnimation } from "./OpenerAnimation.jsx";
import ScrollProgress from "./ScrollProgress.jsx";
import SiteNav from "./SiteNav.jsx";
import { useRevealNav } from "./useRevealNav.js";

function AppInner() {
  const reduceMotion = useReducedMotion();
  const { className: navClassName, pastStory } = useRevealNav({ reduceMotion: !!reduceMotion });

  return (
    <div>
      <OpenerAnimation />
      <ScrollProgress pastStory={pastStory} />

      <a href="#story" className="skip-link">
        Skip to content
      </a>

      <div className="grain grain--dark" aria-hidden="true" />

      <SiteNav className={navClassName} homeAnchor />

      <main id="main" aria-label="6thSense">
        <div id="top" />
        <section id="story" aria-label="6thSense hero">
          <h1 className="visually-hidden">
            6thSense — tactile capture hardware for dexterous robotics
          </h1>
          <ScrollHero />
        </section>
      </main>
    </div>
  );
}

export default function App() {
  return <AppInner />;
}
