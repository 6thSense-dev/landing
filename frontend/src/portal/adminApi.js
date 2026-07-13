/**
 * Admin leads-CRM API calls, layered on the shared portalFetch (cookie auth).
 * Every call hits /api/admin/* which the backend gates to the `admin` role.
 */
import { portalFetch } from "./portalFetch.js";

const apiBase = import.meta.env.VITE_API_URL ?? "";

/** Build the /api/admin/leads querystring from the current view. */
function leadsQuery({ q, status } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status && status !== "all") params.set("status", status);
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function listLeads(view) {
  return portalFetch(`/api/admin/leads${leadsQuery(view)}`);
}

export function createLead(body) {
  return portalFetch("/api/admin/leads", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateLead(id, body) {
  return portalFetch(`/api/admin/leads/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteLead(id) {
  return portalFetch(`/api/admin/leads/${id}`, { method: "DELETE" });
}

/**
 * Download the current view as a CSV. Fetches with credentials (so it works
 * even when the API is a different origin), then saves the blob to disk.
 */
export async function downloadLeadsCsv(view) {
  const res = await fetch(`${apiBase}/api/admin/leads.csv${leadsQuery(view)}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : "6thsense-leads.csv";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Copy the given leads as TSV to the clipboard. Pasting TSV into a Google
 * Sheet (or Excel) drops each field into its own cell — a zero-config
 * "export to Sheets" path.
 */
export async function copyLeadsForSheets(leads) {
  const header = [
    "Name",
    "Email",
    "Organization",
    "Message",
    "Followed up",
    "Followed up at",
    "Received",
  ];
  const clean = (v) => String(v ?? "").replace(/[\t\n\r]+/g, " ").trim();
  const rows = leads.map((l) =>
    [
      clean(l.name),
      clean(l.email),
      clean(l.organization),
      clean(l.message),
      l.followed_up ? "yes" : "no",
      clean(l.followed_up_at),
      clean(l.created_at),
    ].join("\t")
  );
  const tsv = [header.join("\t"), ...rows].join("\n");
  await navigator.clipboard.writeText(tsv);
  return leads.length;
}
