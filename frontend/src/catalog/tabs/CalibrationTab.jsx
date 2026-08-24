/**
 * CalibrationTab — the two blocks a buyer's perception team screens on first.
 * ---------------------------------------------------------------------------
 * Props: { clip }
 *
 * H7 (calibration) and H3 (synchronisation) are hard rejection criteria on most
 * robotics data buys, and this record satisfies both: a named camera model with
 * per-camera intrinsics and distortion, image size, stereo R/T and baseline,
 * shutter type and readout time, cam-IMU extrinsics with an explicit time-offset
 * convention, IMU noise density and random walk, and a per-stream sync table
 * carrying its reference clock, offset sign convention, drift and measured
 * maximum alignment error.
 *
 * All of it was in the payload — including for preview accounts, whose
 * redaction withholds the calibration FILES but not the calibration VALUES —
 * and none of it was rendered anywhere. The only way to see it was "Copy JSON".
 * This tab is pure presentation over data that was already on the wire.
 *
 * Rendering rule, from the contract and applied everywhere: `null` is drawn as
 * an em-dash and means "not determined". A measured 0 is drawn as 0.
 */

import { AlertTriangle } from "lucide-react";

import { formatDuration } from "../format.js";
import { Block, Def, humanise, num } from "./parts.jsx";

/** Camera models we can name in prose. Anything else prints its raw id. */
const CAMERA_MODELS = {
  pinhole: "Pinhole",
  radtan: "Pinhole + radial-tangential",
  kannala_brandt: "Kannala-Brandt (fisheye, k1…k4)",
  equidistant: "Equidistant fisheye",
  double_sphere: "Double sphere",
  omni: "Omnidirectional",
};

/** A 3x3 rotation or a 3-vector, as fixed-width mono rows. */
function Matrix({ rows, digits = 6 }) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const grid = Array.isArray(rows[0]) ? rows : [rows];
  return (
    <div className="cat-cal-mat cat-mono" role="table">
      {grid.map((row, i) => (
        <div className="cat-cal-matrow" role="row" key={i}>
          {(Array.isArray(row) ? row : [row]).map((v, j) => (
            <span role="cell" key={j}>
              {typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—"}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

export default function CalibrationTab({ clip }) {
  const cal = clip?.calibration ?? null;
  const sync = clip?.sync ?? null;
  const cam = cal?.camera ?? null;
  const imu = cal?.imu ?? null;
  const camImu = cal?.cam_imu ?? null;
  const tactile = cal?.tactile ?? null;

  if (!cal && !sync) {
    return (
      <div className="cat-empty">
        <p className="cat-empty__head">No calibration or synchronisation record</p>
        <p className="cat-empty__body">
          This clip ships neither a <code>calibration</code> nor a <code>sync</code> block.
          Without them the two streams cannot be related to each other in space or in time,
          and most buyers treat that as disqualifying (H3, H7) rather than as a gap to fill
          later.
        </p>
      </div>
    );
  }

  const streams = Array.isArray(sync?.streams) ? sync.streams : [];
  const frameMs = clip?.fps ? 1000 / Number(clip.fps) : null;
  const worst = sync?.maximum_alignment_error_ms;
  /* ONE rendering of one measurement. The <dl> printed it at 3 dp ("35.897 ms")
     and the warning 40px underneath printed the same value at 2 ("35.90 ms"),
     which reads as two measurements that disagree — the fastest way to make a
     buyer distrust a QA record. Hoisted so the two cannot drift again. */
  const worstText = num(worst, 3, "ms");
  const overFrame =
    typeof worst === "number" && frameMs != null && Number.isFinite(frameMs)
      ? worst > frameMs
      : false;

  /* A stream that is DELIVERED but is on no shared timeline. The IMU is the case
     this exists for: it carries a free-running t_s and is never stamped on the
     reference clock, so its row was four em-dashes under a header that talks about
     one clock — which reads as a gap in the record rather than as the fact it is.
     Named here, marked in the table, and stated in a note, because an inertial
     stream with no time relation to video cannot do VIO and cannot be fused with
     tactile, and that is the whole reason a buyer wanted it. */
  const unaligned = streams.filter(
    (row) =>
      row &&
      row.stream_id &&
      row.offset_ns == null &&
      row.maximum_alignment_error_ms == null,
  );
  const isUnaligned = (row) => unaligned.indexOf(row) !== -1;

  return (
    <section className="cat-m">
      {/* ---------------- synchronisation (H3) ----------------
          No `aside` on this Block. It carried "independent validation: not
          validated" while the <Def> sixty pixels below carried "INDEPENDENT
          VALIDATION / Not validated" — the same fact twice, and at 360 the aside
          right-aligned into the modal padding and collided with the
          SYNCHRONISATION label, so the duplication also cost a wrap. The <dl>
          keeps it, because that is where a buyer reading the block in order
          meets it. */}
      {sync ? (
        <Block title="Synchronisation">
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def
              label="Max alignment error"
              value={worstText}
              title="The maximum over every measured component: the anchor-fit residual, each stream's rate error carried over the take, and the container timeline's divergence."
            />
            <Def
              label="One video frame"
              value={frameMs != null ? `${frameMs.toFixed(2)} ms` : null}
              title="At this clip's own frame rate. The comparison a buyer makes first."
            />
            <Def label="Clock-fit residual" value={num(sync.clock_fit_residual_ms, 3, "ms")} />
            <Def label="Cross-hand offset" value={num(sync.cross_hand_offset_ms, 3, "ms")} />
            <Def
              label="Samples / video frame"
              value={num(sync.samples_per_video_frame, 2)}
            />
            <Def
              label="Independent validation"
              value={sync.validation_result ? humanise(sync.validation_result) : null}
            />
          </dl>

          {overFrame ? (
            <p className="cat-note cat-note--warn">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                {worstText} exceeds one video frame ({frameMs.toFixed(2)} ms) at{" "}
                {clip.fps} fps. A contact event in this clip is locatable to roughly{" "}
                {Math.ceil(worst / frameMs)} frames, not one.
              </span>
            </p>
          ) : null}

          {/* The sign convention, verbatim. Paraphrasing it is how a buyer's
              loader ends up applying the offset backwards. */}
          {sync.offset_sign_convention ? (
            <p className="cat-m-para cat-mono cat-cal-verbatim">
              {sync.offset_sign_convention}
            </p>
          ) : null}
          {sync.reference_clock_id ? (
            <p className="cat-m-para">
              <span className="cat-label">Reference clock</span>{" "}
              <span>{sync.reference_clock_id}</span>
            </p>
          ) : null}

          {streams.length ? (
            <div className="cat-tablewrap">
              <table className="cat-table">
                <caption className="cat-sr">
                  Per-stream synchronisation: clock, offset, interpolation, drift and measured
                  maximum alignment error.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Stream</th>
                    <th scope="col">Clock</th>
                    <th scope="col" className="cat-table-num">
                      Offset (ns)
                    </th>
                    <th scope="col">Interpolation</th>
                    <th scope="col" className="cat-table-num">
                      Drift (ppm)
                    </th>
                    <th scope="col" className="cat-table-num">
                      Max error (ms)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {streams.map((row, i) => {
                    const err = row.maximum_alignment_error_ms;
                    const bad =
                      typeof err === "number" && frameMs != null && err > frameMs;
                    const off = isUnaligned(row);
                    return (
                      <tr
                        key={row.stream_id || i}
                        className={
                          bad
                            ? "cat-table-row--warn"
                            : off
                              ? "cat-table-row--unaligned"
                              : ""
                        }
                      >
                        <th scope="row" className="cat-mono">
                          {row.stream_id ?? "—"}
                        </th>
                        <td>{row.clock_id ?? <span className="cat-m-def--dash">—</span>}</td>
                        <td className="cat-table-num">
                          {num(row.offset_ns, 0) ?? "—"}
                        </td>
                        <td>{row.interpolation_policy ?? "—"}</td>
                        <td className="cat-table-num">
                          {num(row.estimated_drift_ppm, 2) ?? "—"}
                        </td>
                        <td className="cat-table-num">
                          {num(err, 3) ??
                            (off ? (
                              <span className="cat-table-note">not aligned</span>
                            ) : (
                              "—"
                            ))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}

          {unaligned.length ? (
            <p className="cat-note cat-note--warn">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                {unaligned.map((r) => r.stream_id).join(", ")}{" "}
                {unaligned.length === 1 ? "is" : "are"} delivered but NOT placed on the
                reference clock: no offset and no alignment error exist for{" "}
                {unaligned.length === 1 ? "it" : "them"}, so{" "}
                {unaligned.length === 1 ? "it" : "they"} cannot be fused with the streams
                that are. The per-stream note below says what clock{" "}
                {unaligned.length === 1 ? "it carries" : "they carry"} instead.
              </span>
            </p>
          ) : null}

          {sync.validation_method ? (
            <p className="cat-m-para cat-m-para--muted">{sync.validation_method}</p>
          ) : null}
          {Array.isArray(sync.notes) && sync.notes.length ? (
            <ul className="cat-m-list">
              {sync.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
          {sync.join_recipe ? <p className="cat-m-para">{sync.join_recipe}</p> : null}
          <p className="cat-note">
            An em-dash in this table is a stream whose offset or drift was never estimated. It
            is not zero, and a loader that treats it as zero is guessing.
          </p>
        </Block>
      ) : null}

      {/* ---------------- camera (H7) ---------------- */}
      {cam ? (
        <Block
          title="Camera calibration"
          aside={cam.model ? CAMERA_MODELS[cam.model] || cam.model : null}
        >
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def label="Model" value={cam.model ? CAMERA_MODELS[cam.model] || cam.model : null} />
            <Def
              label="Image size"
              value={
                Array.isArray(cam.image_size)
                  ? `${cam.image_size[0]} × ${cam.image_size[1]} px`
                  : null
              }
            />
            <Def label="Shutter" value={humanise(cam.shutter)} />
            <Def
              label="Readout time"
              value={num(cam.readout_time_ms, 3, "ms")}
              title="Rolling-shutter readout across the frame. Without it, motion on a head-mounted camera cannot be compensated."
            />
            <Def label="Baseline" value={num(cam.stereo?.baseline_m, 5, "m")} />
            <Def label="RMS reprojection" value={num(cam.rms_reprojection_px, 4, "px")} />
            <Def
              label="Rectification residual"
              value={num(cam.rectification_residual_px, 4, "px")}
            />
          </dl>

          {Array.isArray(cam.cameras) && cam.cameras.length ? (
            <div className="cat-tablewrap">
              <table className="cat-table">
                <caption className="cat-sr">
                  Per-camera intrinsics and distortion coefficients.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Camera</th>
                    <th scope="col">Role</th>
                    <th scope="col" className="cat-table-num">
                      fx
                    </th>
                    <th scope="col" className="cat-table-num">
                      fy
                    </th>
                    <th scope="col" className="cat-table-num">
                      cx
                    </th>
                    <th scope="col" className="cat-table-num">
                      cy
                    </th>
                    <th scope="col">Distortion</th>
                  </tr>
                </thead>
                <tbody>
                  {cam.cameras.map((c, i) => (
                    <tr key={c.id || i}>
                      <th scope="row" className="cat-mono">
                        {c.id ?? "—"}
                      </th>
                      <td>{humanise(c.role) ?? "—"}</td>
                      <td className="cat-table-num">{num(c.fx, 4) ?? "—"}</td>
                      <td className="cat-table-num">{num(c.fy, 4) ?? "—"}</td>
                      <td className="cat-table-num">{num(c.cx, 4) ?? "—"}</td>
                      <td className="cat-table-num">{num(c.cy, 4) ?? "—"}</td>
                      <td className="cat-num cat-cal-dist">
                        {Array.isArray(c.distortion) && c.distortion.length
                          ? c.distortion.map((d) => num(d, 8)).join(", ")
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {cam.stereo ? (
            <div className="cat-cal-pair">
              <div>
                <p className="cat-label">Stereo rotation R</p>
                <Matrix rows={cam.stereo.R} />
              </div>
              <div>
                <p className="cat-label">Stereo translation T (m)</p>
                <Matrix rows={cam.stereo.T} />
              </div>
            </div>
          ) : null}

          {cam.note ? <p className="cat-m-para">{cam.note}</p> : null}
        </Block>
      ) : null}

      {/* ---------------- camera ↔ IMU extrinsics ---------------- */}
      {camImu ? (
        <Block title="Camera ↔ IMU extrinsics">
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def label="Time offset" value={num(camImu.time_offset_s, 6, "s")} />
            <Def label="Convention" value={camImu.time_offset_convention} mono />
          </dl>
          <div className="cat-cal-pair">
            <div>
              <p className="cat-label">Rotation R</p>
              <Matrix rows={camImu.R} digits={5} />
            </div>
            <div>
              <p className="cat-label">Translation T (m)</p>
              <Matrix rows={camImu.T} digits={6} />
            </div>
          </div>
        </Block>
      ) : null}

      {/* ---------------- IMU ---------------- */}
      {imu ? (
        <Block title="IMU" aside={imu.status ? humanise(imu.status) : null}>
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def label="Part" value={imu.model} mono />
            <Def label="Status" value={humanise(imu.status)} />
            <Def label="Rate" value={num(imu.rate_hz, 1, "Hz")} />
            <Def label="Axes" value={num(imu.axes, 0)} />
            <Def label="Accel range" value={num(imu.accel_range_g, 1, "g")} />
            <Def label="Gyro range" value={num(imu.gyro_range_dps, 1, "dps")} />
            <Def label="Accel noise density" value={num(imu.accel_noise_density, 9)} />
            <Def label="Accel random walk" value={num(imu.accel_random_walk, 9)} />
            <Def label="Gyro noise density" value={num(imu.gyro_noise_density, 9)} />
            <Def label="Gyro random walk" value={num(imu.gyro_random_walk, 9)} />
          </dl>
          {imu.units_note ? (
            <p className="cat-m-para cat-m-para--muted cat-mono">{imu.units_note}</p>
          ) : null}
        </Block>
      ) : null}

      {/* ---------------- tactile geometry ---------------- */}
      {tactile ? (
        <Block title="Tactile geometry">
          <dl className="cat-m-defs cat-m-defs--tight">
            <Def
              label="Grid"
              value={
                Array.isArray(tactile.grid) ? `${tactile.grid[0]} × ${tactile.grid[1]}` : null
              }
            />
            <Def label="Taxel pitch" value={num(tactile.taxel_pitch_mm, 2, "mm")} />
            <Def
              label="Force calibration"
              value={tactile.force_calibration ? humanise(tactile.force_calibration) : null}
            />
          </dl>
          {tactile.index_rule ? (
            <p className="cat-m-para cat-mono cat-cal-verbatim">{tactile.index_rule}</p>
          ) : null}
        </Block>
      ) : null}

      {clip?.duration_s != null ? (
        <p className="cat-note">
          Every figure above is per-clip and measured on this take ({formatDuration(clip.duration_s)}
          ), not a specification for the rig. Two clips from the same device can and do differ.
        </p>
      ) : null}
    </section>
  );
}
