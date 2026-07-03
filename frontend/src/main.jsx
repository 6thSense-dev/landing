import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App";
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

// Strip the build-time SEO prerender shell before client render so JS users
// and screen readers don't get duplicate content (see scripts/seoPrerenderPlugin.js).
document.getElementById("seo-prerender")?.remove();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={<div className="portal-loading" aria-hidden />}>
        <Routes>
          <Route element={<PortalLayout />}>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/portal/*" element={<PortalApp />} />
          </Route>
          <Route path="/product" element={<ProductPage slug="/product" />} />
          <Route path="/product/gloves" element={<ProductPage slug="/product/gloves" />} />
          <Route path="/product/skin" element={<ProductPage slug="/product/skin" />} />
          <Route path="/product/rig" element={<ProductPage slug="/product/rig" />} />
          <Route path="/products" element={<ProductsShowcase />} />
          <Route path="/*" element={<App />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
