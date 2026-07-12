import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence } from "framer-motion";

import App from "./App";
import PageTransition from "./PageTransition.jsx";
import "./styles.css";
import "./scroll-hero.css";
import "./portal/portal.css";

const LoginPage = lazy(() => import("./portal/LoginPage.jsx"));
const PortalApp = lazy(() => import("./portal/PortalApp.jsx"));
const PortalLayout = lazy(() => import("./portal/PortalLayout.jsx"));

// Secondary product pages — reachable by URL + sitemap for crawling; not yet
// linked from the homepage nav. Each has a build-time crawlable static HTML
// variant (see scripts/seoPrerenderPlugin.js).
const ProductPage = lazy(() => import("./pages/ProductPage.jsx"));

// Designed, human-facing product showcase (distinct from the text-only SEO
// pages above). Presents the hardware line as editorial feature rows.
const ProductsShowcase = lazy(() => import("./pages/ProductsShowcase.jsx"));

// Placeholder section linked from the nav ("People" — real content later).
const PeoplePage = lazy(() => import("./pages/PeoplePage.jsx"));

// TEMPORARY: interactive alignment tool for the Skin composite (/skin-tune).
// Remove this + the route below once the robotic/glove alignment is locked in.
const SkinTune = lazy(() => import("./pages/SkinTune.jsx"));
const RoboShot = lazy(() => import("./pages/RoboShot.jsx"));

// Strip the build-time SEO prerender shell before client render so JS users
// and screen readers don't get duplicate content (see scripts/seoPrerenderPlugin.js).
document.getElementById("seo-prerender")?.remove();

// Every top-level page fades the same way (see PageTransition.jsx). Keyed on
// the first path segment, not the full pathname, so navigating within the
// portal (e.g. between dashboard tabs) doesn't retrigger a full-page fade —
// only crossing between Home/Products/People/Partner-login/etc. does.
function AnimatedRoutes() {
  const location = useLocation();
  const routeKey = location.pathname.split("/")[1] || "home";
  return (
    <AnimatePresence mode="wait" initial={false}>
      <Routes location={location} key={routeKey}>
        <Route element={<PortalLayout />}>
          <Route path="/login" element={<PageTransition><LoginPage /></PageTransition>} />
          <Route path="/portal/*" element={<PageTransition><PortalApp /></PageTransition>} />
        </Route>
        <Route path="/product" element={<PageTransition><ProductPage slug="/product" /></PageTransition>} />
        <Route path="/product/gloves" element={<PageTransition><ProductPage slug="/product/gloves" /></PageTransition>} />
        <Route path="/product/skin" element={<PageTransition><ProductPage slug="/product/skin" /></PageTransition>} />
        <Route path="/product/rig" element={<PageTransition><ProductPage slug="/product/rig" /></PageTransition>} />
        <Route path="/products" element={<PageTransition><ProductsShowcase /></PageTransition>} />
        <Route path="/skin-tune" element={<PageTransition><SkinTune /></PageTransition>} />
        <Route path="/robo-shot" element={<PageTransition><RoboShot /></PageTransition>} />
        <Route path="/people" element={<PageTransition><PeoplePage /></PageTransition>} />
        <Route path="/*" element={<PageTransition><App /></PageTransition>} />
      </Routes>
    </AnimatePresence>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={<div className="portal-loading" aria-hidden />}>
        <AnimatedRoutes />
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
