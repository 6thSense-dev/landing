import { lazy, Suspense } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "./useSession.jsx";
import { WorkspacePreviewContext } from "./WorkspaceContext.jsx";
import OpsDashboard from "./OpsDashboard.jsx";
import CustomerHome from "./CustomerHome.jsx";
import InvestorHome from "./InvestorHome.jsx";
import { FounderOverview } from "./FounderOverview.jsx";
import { FounderSettings } from "./FounderSettings.jsx";
import { ComingSoon } from "./ComingSoon.jsx";
import IntakeReviewLink from "./IntakeReviewLink.jsx";
import "../catalog/catalog.css";
import "./workspace.css";

const CatalogPage = lazy(() => import("../catalog/CatalogPage.jsx"));
const ROLES = {
  guest: { name: "Guest", home: "Catalog", text: "The buyer preview. Guests browse published clips with restricted data access; they cannot open Operations or manage collectors.", views: ["catalog"] },
  ops: { name: "Operations", home: "Collector Operations", text: "The collection team’s recording ledger: assign collectors, label tasks and track approvals and payment flags. This role cannot browse the buyer Catalog.", views: ["ops"] },
  admin: { name: "Admin", home: "Leads · your account opens Workspace", text: "Admins manage website leads and can open Catalog and Operations. Only your account has this Workspace and the enabled private Intake review.", views: ["home", "catalog", "ops"] },
  founder: { name: "Founder", home: "Founder overview", text: "The founder home is mostly placeholders. Catalog and Operations are allowed by the role, although the existing founder sidebar does not link to them.", views: ["home", "catalog", "ops"] },
  customer: { name: "Customer", home: "Customer home", text: "The existing customer home is a welcome placeholder. Catalog access permits customer-level data; access still depends on each clip’s published permissions.", views: ["home", "catalog"] },
  investor: { name: "Investor", home: "Investor home", text: "The existing investor home is a welcome placeholder. Catalog access uses the same restricted data view as Guest.", views: ["home", "catalog"] },
};
const WORK = [
  { title: "Collector Operations", path: "/portal/ops", tag: "Live recording ledger", text: "Find raw recordings, assign collectors and inspect recording details. Recorded minutes are not verified usable hours.", action: "Open Operations" },
  { title: "Buyer Catalog", path: "/portal/catalog", tag: "Published collection", text: "Browse the current published collection and clip details. This is a separate inventory from Operations; raw uploads do not automatically appear here.", action: "Open Catalog" },
  { title: "Website leads", path: "/portal/admin", tag: "Live inquiries", text: "Review inbound website inquiries and their follow-up status. This is not the recording or payment board.", action: "Open leads" },
];

export default function Workspace() {
  const { user, logout } = useSession();
  const { "*": path = "" } = useParams();
  const [params] = useSearchParams();
  if (!user?.workspace_enabled) return <Navigate to="/portal" replace />;
  const match = /^learn\/(guest|ops|admin|founder|customer|investor)$/.exec(path);
  if (path && !match) return <Navigate to="/portal/workspace" replace />;
  if (match) return <RolePreview key={match[1] + ":" + (params.get("view") || "")} role={match[1]} />;
  return <div className="cat-root workspace">
    <header className="workspace-bar"><Link to="/" className="workspace-brand">6THSENSE</Link><span>Workspace</span><span className="workspace-account">{user.email} · Admin</span><button onClick={logout}>Sign out</button></header>
    <main className="workspace-main">
      <p className="workspace-eyebrow">Your private workspace</p>
      <h1>One login. Know where you are.</h1>
      <p className="workspace-lede">Learn what each account sees, then open the right tool to work. You stay signed in as yourself throughout.</p>
      <section aria-labelledby="learn-title" className="workspace-section">
        <div className="workspace-section-heading"><span className="workspace-step">01</span><div><h2 id="learn-title">Learn the accounts</h2><p>Safe, read-only views. No shared passwords or account switching.</p></div></div>
        <div className="workspace-roles">{Object.entries(ROLES).map(([role, r]) => <Link key={role} to={`/portal/workspace/learn/${role}`} className="workspace-role"><strong>{r.name}</strong><span>Starts at {r.home}</span><span className="workspace-action">Explore view →</span></Link>)}</div>
      </section>
      <section aria-labelledby="work-title" className="workspace-section">
        <div className="workspace-section-heading"><span className="workspace-step">02</span><div><h2 id="work-title">Open a tool to work</h2><p>These are your real admin tools. Changes here can affect live records.</p></div></div>
        <div className="workspace-tools">{WORK.map(w => <article className="workspace-tool" key={w.path}><p className="workspace-eyebrow">{w.tag}</p><h3>{w.title}</h3><p>{w.text}</p><Link to={w.path}>{w.action} →</Link></article>)}
          <article className="workspace-tool"><p className="workspace-eyebrow">Synthetic prototype</p><h3>Intake review</h3><p>Practice selecting activity intervals on test footage. This does not crop real recordings or calculate today’s collector payments.</p><IntakeReviewLink className="workspace-intake" /></article>
        </div>
      </section>
      <aside className="workspace-note"><h2>Payday needs a separate check</h2><p>You confirmed today’s collectors are paid per usable hour. Operations currently stores an episode-based payment rate and recorded minutes. Neither is an approved usable-hour total. Preserve historical agreements; manual interval review and hourly reconciliation still need connecting to real recordings.</p></aside>
    </main>
  </div>;
}

function RolePreview({ role }) {
  const { user } = useSession();
  const [params] = useSearchParams();
  const r = ROLES[role];
  const requested = params.get("view");
  const view = r.views.includes(requested) ? requested : r.views[0];
  const founderTab = ["Overview", "Meetings", "Followups", "Whiteboard", "Settings"].includes(params.get("tab")) ? params.get("tab") : "Overview";
  return <WorkspacePreviewContext.Provider value={role}>
    <div className="cat-root workspace-preview">
      <header className="workspace-preview-banner"><div><strong>Learning preview · {r.name} · Read-only</strong><span>Signed in as {user.email}. No account or permission changes.</span></div><Link to="/portal/workspace">Exit preview →</Link></header>
      <section className="workspace-preview-guide"><p className="workspace-eyebrow">Partner login → {r.home}</p><h1>What {r.name.toLowerCase()} sees</h1><p>{r.text}</p>
        <nav aria-label="Account areas">{r.views.map(v => <Link key={v} aria-current={view === v ? "page" : undefined} to={`?view=${v}`}>{v === "home" ? "Starting screen" : v === "ops" ? "Operations" : "Catalog"}</Link>)}</nav>
        {view === "ops" && <p className="workspace-preview-caution">The real Operations layout and current records, with writing disabled. Payment flags are bookkeeping, not proof of a settled transfer. Its minutes are full recording duration, not cropped usable time.</p>}
        {view === "catalog" && <p className="workspace-preview-caution">The actual Catalog components with {r.name.toLowerCase()} permissions applied by the server. Any synthetic labels belong to the published collection; this is not the raw Operations inventory.</p>}
      </section>
      {view === "catalog" ? <Suspense fallback={<p className="workspace-loading">Loading Catalog…</p>}><CatalogPage key={role} previewRole={role} /></Suspense> : view === "ops" ? <OpsDashboard readOnly /> : role === "customer" ? <CustomerHome /> : role === "investor" ? <InvestorHome /> : role === "founder" ? <div className="portal-shell"><aside className="portal-sidebar"><div className="portal-sidebar-brand">6THSENSE</div><div className="portal-sidebar-greeting">Hi, {user.name}</div><nav>{["Overview","Meetings","Followups","Whiteboard","Settings"].map(tab => <Link key={tab} to={`?view=home&tab=${tab}`} aria-current={founderTab === tab ? "page" : undefined}>{tab}</Link>)}</nav></aside><main className="portal-main">{founderTab === "Overview" ? <FounderOverview /> : founderTab === "Settings" ? <><p>Settings displays your own identity. Your actual role remains Admin.</p><FounderSettings /></> : <ComingSoon name={founderTab} />}</main></div> : <section className="workspace-admin-home"><h2>Your admin starting screen is Workspace</h2><p>Other admins still start at the leads dashboard. This guide does not expose their accounts or alter permissions. Use the work links outside preview to manage your live leads, recordings, or published Catalog.</p><Link to="/portal/workspace">Return to your work tools →</Link></section>}
    </div>
  </WorkspacePreviewContext.Provider>;
}
