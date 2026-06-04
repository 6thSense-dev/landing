import { useReducedMotion } from "framer-motion";
import { Link } from "react-router-dom";
import { ScrollHero } from "./ScrollHero.jsx";
import { OpenerAnimation } from "./OpenerAnimation.jsx";
import ScrollProgress from "./ScrollProgress.jsx";
import { useRevealNav } from "./useRevealNav.js";

function AppInner() {
  const reduceMotion = useReducedMotion();
  const { className: navClassName, pastStory } = useRevealNav({ reduceMotion: !!reduceMotion });

  return (
    <>
      <OpenerAnimation />
      <ScrollProgress pastStory={pastStory} />

      <a href="#story" className="skip-link">
        Skip to content
      </a>

      <div className="grain grain--dark" aria-hidden="true" />

      <header className={navClassName} role="banner">
        <nav className="nav-flagship-inner" aria-label="Primary">
          <a className="wordmark wordmark-on-dark" href="#top" aria-label="6thSense home">
            <img
              className="nav-logo"
              src="/logos/Logo_Alpha.png"
              alt=""
              aria-hidden="true"
            />
            <span className="nav-logo-text">6THSENSE</span>
          </a>
          <div className="nav-links nav-links-on-dark">
            <Link to="/login" className="nav-cta nav-cta-on-dark">
              Partner login
            </Link>
          </div>
        </nav>
      </header>

      <main id="main" aria-label="6thSense">
        <div id="top" />
        <section id="story" aria-label="6thSense hero">
          <h1 className="visually-hidden">
            6thSense — tactile egocentric datasets for dexterous robotics
          </h1>
          <ScrollHero />
        </section>
      </main>
    </>
  );
}

export default function App() {
  return <AppInner />;
}
