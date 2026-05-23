import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App";
import "./styles.css";
import "./scroll-hero.css";
import "./portal/portal.css";

const LoginPage = lazy(() => import("./portal/LoginPage.jsx"));
const PortalApp = lazy(() => import("./portal/PortalApp.jsx"));

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={<div className="portal-loading" aria-hidden />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/portal/*" element={<PortalApp />} />
          <Route path="/*" element={<App />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
