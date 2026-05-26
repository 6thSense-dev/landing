/**
 * Thin fetch wrapper for portal API calls.
 *
 * - Prepends VITE_API_URL so cookies are sent to the right origin.
 * - Always sends `credentials: "include"` so the sid cookie travels with the
 *   request (the API and the site may be different origins on Railway).
 * - Returns a normalized `{ok, status, data}` object.
 */
const apiBase = import.meta.env.VITE_API_URL ?? "";

export async function portalFetch(path, opts = {}) {
  const init = {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(opts.body && !(opts.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(opts.headers || {}),
    },
    ...opts,
  };
  let res;
  try {
    res = await fetch(`${apiBase}${path}`, init);
  } catch {
    return { ok: false, status: 0, data: null };
  }
  let data = null;
  if (res.status !== 204) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  }
  return { ok: res.ok, status: res.status, data };
}
