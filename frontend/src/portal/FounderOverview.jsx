import { useSession } from "./useSession.js";

export function FounderOverview() {
  const { user } = useSession();
  return (
    <section className="portal-overview">
      <h2>Welcome back{user?.name ? `, ${user.name}` : ""}.</h2>
      <div className="portal-overview-grid">
        <article className="portal-card">
          <h3>Meetings</h3>
          <p>Coming in next cycle.</p>
        </article>
        <article className="portal-card">
          <h3>Followups</h3>
          <p>Coming in next cycle.</p>
        </article>
        <article className="portal-card">
          <h3>Whiteboard</h3>
          <p>Coming in next cycle.</p>
        </article>
      </div>
    </section>
  );
}
