import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { portalFetch } from "./portalFetch.js";

const SessionCtx = createContext(null);

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

  const login = useCallback(async (email, password) => {
    const { ok, status, data } = await portalFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (ok && data?.user) {
      setState({ status: "authed", user: data.user });
      return { ok: true, user: data.user };
    }
    return { ok: false, status, error: data?.error || "Login failed." };
  }, []);

  const logout = useCallback(async () => {
    await portalFetch("/api/auth/logout", { method: "POST" });
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
