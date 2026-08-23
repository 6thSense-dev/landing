import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { portalFetch } from "./portalFetch.js";

const SessionCtx = createContext(null);

/**
 * Broadcast that the signed-in identity changed.
 *
 * A window event rather than an import: the catalog is a lazily loaded chunk and
 * a static import here would pull ~3000 lines of it into the portal's main
 * bundle for every founder who never opens it. Any module holding
 * identity-scoped state listens for this and drops it — see
 * `catalog/useCatalog.js`, whose module cache holds server-redacted documents and
 * live presigned URLs that belong to exactly one role.
 *
 * The catalog ALSO keys its cache on the identity it is rendered with, so this
 * event is defence in depth and not the only barrier: a listener that never
 * registered (chunk not loaded) means there is no cache to leak either.
 */
export const SESSION_CHANGED_EVENT = "6s-portal:session-changed";

function announceSession(user) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(SESSION_CHANGED_EVENT, {
      detail: user ? `${user.id}:${user.role}` : null,
    }),
  );
}

export function SessionProvider({ children }) {
  const [state, setState] = useState({ status: "loading", user: null });

  const refresh = useCallback(async () => {
    const { ok, status, data } = await portalFetch("/api/auth/me");
    if (ok && data) {
      setState({ status: "authed", user: data });
    } else if (status === 401) {
      setState({ status: "anon", user: null });
    } else {
      setState({ status: "error", user: null });
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  /**
   * `identifier` is an email address or the `guest` demo username.
   *
   * The wire format sends BOTH keys, and which ones are present is deliberate:
   *
   *  - `identifier` is always sent. It is the field the API reads.
   *  - `email` is sent only when the value actually contains an "@". The
   *    pre-catalog API required `email` and typed it as a strict `EmailStr`,
   *    so including it keeps real partner logins working against a backend
   *    that has not been redeployed yet — while omitting it for `guest` keeps
   *    that validator from ever seeing a value it would reject with a 422.
   *
   * Pydantic ignores unknown keys by default, so neither half of this costs
   * anything on the version of the API that does not need it.
   */
  const login = useCallback(async (identifier, password) => {
    const body = { identifier, password };
    if (identifier.includes("@")) body.email = identifier;
    const { ok, status, data } = await portalFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (ok && data?.user) {
      // Before the state update, so nothing renders against another identity's
      // cache: a login can switch identity with no logout and no reload.
      announceSession(data.user);
      setState({ status: "authed", user: data.user });
      return { ok: true, user: data.user };
    }
    return { ok: false, status, error: data?.error || "Login failed." };
  }, []);

  const logout = useCallback(async () => {
    await portalFetch("/api/auth/logout", { method: "POST" });
    announceSession(null);
    setState({ status: "anon", user: null });
  }, []);

  return (
    <SessionCtx.Provider value={{ ...state, refresh, login, logout }}>
      {children}
    </SessionCtx.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
