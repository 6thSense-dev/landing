import { useSession } from "./useSession.js";

export function FounderSettings() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <section className="portal-settings">
      <h2>Account</h2>
      <dl>
        <dt>Name</dt><dd>{user.name}</dd>
        <dt>Email</dt><dd>{user.email}</dd>
        <dt>Role</dt><dd>{user.role}</dd>
      </dl>
    </section>
  );
}
