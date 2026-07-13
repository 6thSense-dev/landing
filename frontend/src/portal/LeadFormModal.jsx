import { useEffect, useState } from "react";

/**
 * Add / edit modal for a single lead. Passing `lead` puts it in edit mode;
 * `null` is add mode. `onSave(form)` returns {ok} or {ok:false, error}.
 */
export default function LeadFormModal({ lead, onSave, onClose }) {
  const isEdit = Boolean(lead);
  const [form, setForm] = useState({
    name: lead?.name ?? "",
    email: lead?.email ?? "",
    organization: lead?.organization ?? "",
    message: lead?.message ?? "",
    followed_up: lead?.followed_up ?? false,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    if (!form.name.trim() || !form.email.trim() || !form.organization.trim() || !form.message.trim()) {
      setError("All fields are required.");
      return;
    }
    if (!form.email.includes("@")) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    const res = await onSave({
      name: form.name.trim(),
      email: form.email.trim().toLowerCase(),
      organization: form.organization.trim(),
      message: form.message.trim(),
      followed_up: form.followed_up,
    });
    setBusy(false);
    if (!res.ok) setError(res.error || "Couldn't save.");
  }

  return (
    <div className="admin-modal-overlay" onClick={onClose}>
      <div
        className="admin-modal"
        role="dialog"
        aria-modal="true"
        aria-label={isEdit ? "Edit lead" : "Add lead"}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="admin-modal-x" onClick={onClose} aria-label="Close" type="button">×</button>
        <h2 className="admin-modal-title">{isEdit ? "Edit lead" : "Add lead"}</h2>
        <form className="admin-form" onSubmit={onSubmit} noValidate>
          <label className="admin-field">
            <span>Name</span>
            <input value={form.name} onChange={set("name")} autoComplete="off" />
          </label>
          <label className="admin-field">
            <span>Email</span>
            <input type="email" value={form.email} onChange={set("email")} autoComplete="off" />
          </label>
          <label className="admin-field">
            <span>Organization</span>
            <input value={form.organization} onChange={set("organization")} autoComplete="off" />
          </label>
          <label className="admin-field">
            <span>Message</span>
            <textarea rows={4} value={form.message} onChange={set("message")} />
          </label>
          <label className="admin-check-inline">
            <input
              type="checkbox"
              checked={form.followed_up}
              onChange={(e) => setForm((f) => ({ ...f, followed_up: e.target.checked }))}
            />
            <span>Already followed up</span>
          </label>

          {error && <p className="admin-form-error" role="alert">{error}</p>}

          <div className="admin-modal-actions">
            <button type="button" className="admin-btn admin-btn--ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="admin-btn admin-btn--solid" disabled={busy}>
              {busy ? "Saving…" : isEdit ? "Save changes" : "Add lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
