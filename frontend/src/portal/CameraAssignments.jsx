import { useState } from "react";

export default function CameraAssignments({ state, act, busy }) {
  const [device, setDevice] = useState("");
  const [wearer, setWearer] = useState("");
  const [backfill, setBackfill] = useState(false);
  const [message, setMessage] = useState("");
  const people = state.wearers || [];
  return (
    <details className="ops-panel ops-pbody">
      <summary>Camera assignments ({state.cameras?.length || 0})</summary>
      <div className="ops-tablewrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Camera</th>
              <th>Contributor</th>
              <th>Workplace</th>
            </tr>
          </thead>
          <tbody>
            {(state.cameras || []).map((c) => {
              const p = people.find((w) => w.id === c.wearer_id);
              return (
                <tr key={c.device_id}>
                  <td>EGO-{c.device_id}</td>
                  <td>{p?.name || "Unassigned"}</td>
                  <td>{p?.workplace || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <form
        className="ops-pbody"
        onSubmit={async (e) => {
          e.preventDefault();
          setMessage("");
          const saved = await act("camera", "/api/ops/clean/cameras", {
            device_id: device,
            wearer_id: Number(wearer),
            assign_unassigned_recordings: backfill,
          });
          if (saved) {
            setMessage("Camera assignment saved.");
            setDevice("");
            setBackfill(false);
          }
        }}
      >
        <label htmlFor="user-camera">Camera</label>
        <input
          id="user-camera"
          placeholder="EGO-ABC123"
          value={device}
          onChange={(e) => setDevice(e.target.value)}
          required
          maxLength={32}
        />
        <label htmlFor="camera-contributor">Contributor</label>
        <select
          id="camera-contributor"
          value={wearer}
          onChange={(e) => setWearer(e.target.value)}
          required
        >
          <option value="">Choose a contributor</option>
          {people
            .filter((p) => p.is_active)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.workplace}
              </option>
            ))}
        </select>
        <label className="ops-check">
          <input
            type="checkbox"
            checked={backfill}
            onChange={(e) => setBackfill(e.target.checked)}
          />
          I verified this person also collected the existing unassigned raw
          recordings from this camera.
        </label>
        <button disabled={!!busy || !device || !wearer}>
          Save camera assignment
        </button>
        <p className="ops-hint">
          Previously assigned footage and payment history keep their
          contributor. This is supervised assignment; app ownership verification
          remains separate.
        </p>
        {message && <p role="status">{message}</p>}
      </form>
    </details>
  );
}
