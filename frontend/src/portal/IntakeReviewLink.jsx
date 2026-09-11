import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { portalFetch } from "./portalFetch.js";
import { useSession } from "./useSession.jsx";

export default function IntakeReviewLink() {
  const { user } = useSession();
  const [identity, setIdentity] = useState(null);
  const key = user ? `${user.id}:${user.role}:${user.email}` : null;
  useEffect(() => {
    let active = true;
    setIdentity(null);
    if (user?.role === "admin") portalFetch("/api/ops/intake-review/capability").then(r => {
      if (active && r.ok && r.data?.enabled === true) setIdentity(key);
    });
    return () => { active = false; };
  }, [key, user?.role]);
  return key && identity === key ? <Link className="cat-topbar__logout" to="/portal/intake-review">Intake review</Link> : null;
}
