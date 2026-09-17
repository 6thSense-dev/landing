import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Check, CheckCircle2, FolderUp, LockKeyhole, Pause, Upload, X } from "lucide-react";
import { bytes, droppedFiles, groupEpisodes } from "./files.js";
import { transferEpisode, uploadApi } from "./transfer.js";
import SignIn from "./SignIn.jsx";
import Activate, { linkFormContract } from "./Activate.jsx";
import { contributorSession as session } from "./auth.js";
import { copy } from "./copy.js";
import "./upload.css";

export default function UploadPage() {
  const [locale, setLocale] = useState(navigator.language.startsWith("ko") ? "ko" : "en");
  const t = copy[locale];
  const [signedIn, setSignedIn] = useState(session.signedIn);
  const [info, setInfo] = useState(null);
  const [formConfig, setFormConfig] = useState(undefined);
  const [phoneVerified, setPhoneVerified] = useState(false);
  const [activation, setActivation] = useState(new URLSearchParams(location.search).get('activate') === '1');
  const [error, setError] = useState("");
  const [queue, setQueue] = useState([]);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [ignored, setIgnored] = useState(0);
  const picker = useRef(null);
  const controller = useRef(null);
  const allDone = queue.length > 0 && queue.every(e => e.status === "complete");

  useEffect(() => {
    document.title = "Upload episodes · 6thSense";
    const tags = ["robots", "referrer"].map((name, i) => {
      const tag = document.createElement("meta"); tag.name = name;
      tag.content = i === 0 ? "noindex, nofollow" : "no-referrer";
      document.head.appendChild(tag); return tag;
    });
    const unsubscribe = session.subscribe(setSignedIn);
    return () => { unsubscribe(); controller.current?.abort(); tags.forEach(tag => tag.remove()); };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    fetch(`${import.meta.env.VITE_API_URL ?? ''}/api/form-contracts/configuration`, {credentials:'omit',signal:abort.signal})
      .then(r=>r.ok?r.json():null).then(setFormConfig).catch(()=>{if(!abort.signal.aborted)setFormConfig(null);});
    return ()=>abort.abort();
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    setInfo(null); setError(""); setQueue([]);
    if (signedIn && formConfig !== undefined) (formConfig ? linkFormContract(abort.signal).catch(e=>{if(!['contract_not_found','contract_region_mismatch'].includes(e.message))throw e;}) : Promise.resolve()).then(()=>uploadApi(session, "/info", undefined, abort.signal)).then(setInfo).catch(e => {
      if (!abort.signal.aborted) setError(e.message);
    });
    return () => abort.abort();
  }, [signedIn, formConfig]);

  const signOut = async () => {
    controller.current?.abort();
    try { await session.signOut(); }
    catch { setError(t.errors.signout_retry); }
  };

  useEffect(() => {
    const protect = event => { event.preventDefault(); event.returnValue = ""; };
    if (busy) window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [busy]);

  const accept = async input => {
    if (busy || reading) return;
    setReading(true); setError("");
    try {
      const selected = groupEpisodes(await input);
      setIgnored(selected.ignored);
      setQueue(previous => {
        const combined = new Map(previous.map(e => [e.recording, e]));
        for (const e of selected.episodes) if (combined.get(e.recording)?.status !== "complete") {
          combined.set(e.recording, { ...e, status: "ready", loaded: 0 });
        }
        return [...combined.values()];
      });
    } catch (e) { setError(e.message); }
    finally { setReading(false); }
  };

  const update = (recording, patch) => setQueue(q => q.map(e => e.recording === recording ? { ...e, ...patch } : e));
  const start = async () => {
    if (busy || !info) return;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError("");
    for (const episode of queue.filter(e => e.status !== "complete")) {
      if (abort.signal.aborted) break;
      update(episode.recording, { status: "preparing" });
      try {
        await transferEpisode(session, episode, loaded => {
          if (!abort.signal.aborted) update(episode.recording, { loaded, status: "uploading" });
        }, abort.signal);
        update(episode.recording, { status: "complete", loaded: episode.bytes });
      } catch (e) {
        abort.abort();
        update(episode.recording, { status: e.name === "AbortError" ? "paused" : "failed" });
        if (e.name !== "AbortError") setError(e.message);
        break;
      }
    }
    setBusy(false);
    uploadApi(session, "/info").then(setInfo).catch(() => {});
  };

  return (
    <div className="upload-page" lang={locale}>
      <div className="upload-frame">
        <header className="upload-nav">
          <a href="/" className="upload-brand" aria-label="6thSense home">6thSense<span /></a>
          <button className="upload-language" onClick={() => setLocale(locale === "en" ? "ko" : "en")}>{locale === "en" ? "한국어" : "English"}</button>
        </header>
        <main>
          <section className="upload-intro">
            <p className="upload-eyebrow"><span />{t.eyebrow}</p>
            <h1>{t.title}</h1><p>{t.intro}</p>
          </section>
          {!signedIn ? <>{activation && formConfig ? <Activate locale={locale} back={verified=>{setPhoneVerified(verified);setActivation(false);}}/> : <>{phoneVerified && <p role="status">{t.phoneVerified}</p>}<SignIn t={t} />{formConfig && <div className="upload-signin"><button className="upload-button" onClick={()=>setActivation(true)}>{locale==='ko'?'회원가입':'Sign up'}</button><p><a href={formConfig.url} target="_blank" rel="noreferrer">{locale==='ko'?'참여 계약 양식':'Contributor contract form'}</a></p></div>}</>}{error && <p className="upload-error" role="alert">{t.errors[error] || error}</p>}</> : !info ? (
            <section className="upload-access" role={error ? "alert" : "status"}><LockKeyhole size={28} /><h2>{error ? (t.errors[error] || error) : t.loading}</h2>{error && <p><a href="mailto:alex@6thsense.dev">alex@6thsense.dev <ArrowUpRight size={16} /></a></p>}<button className="upload-text-button" onClick={signOut}>{t.signOut}</button></section>
          ) : <>
            <section className="upload-identity" aria-label={t.for}>
              <div className="upload-avatar">{info.name.slice(0, 1)}</div>
              <div><span className="upload-caption">{t.for}</span><strong>{info.name}</strong></div>
              <button className="upload-text-button upload-signout" onClick={signOut} disabled={busy}>{t.signOut}</button>
              <LockKeyhole size={18} aria-label={t.private} />
            </section>
            <div className="upload-workspace">
              <div className="upload-primary">
                <section className={`upload-drop${dragging ? " is-dragging" : ""}${busy ? " is-busy" : ""}`}
                  onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }}
                  onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
                  onDrop={event => { event.preventDefault(); setDragging(false); if (!busy && !reading) accept(droppedFiles(event.dataTransfer.items)); }}>
                  <div className="upload-drop-icon"><FolderUp size={34} strokeWidth={1.5} /></div>
                  <h2>{reading ? t.checking : t.drop}</h2><p>{t.hint}</p>
                  <button className="upload-button" disabled={busy || reading} onClick={() => picker.current.click()}><Upload size={17} />{t.choose}</button>
                  <input ref={picker} type="file" webkitdirectory="" directory="" multiple hidden aria-label={t.choose}
                    onChange={event => { const files = [...event.target.files].map(file => ({ file, path: file.webkitRelativePath || file.name })); event.target.value = ""; accept(files); }} />
                  <span className="upload-caption">{t.original}</span>
                </section>
                {error && <p className="upload-error" role="alert">{t.errors[error] || error}</p>}
                {ignored > 0 && <p className="upload-caption">{ignored} {t.ignored}</p>}
                {queue.length > 0 && <section className="upload-queue" aria-label={t.queue}>
                  <div className="upload-queue-heading"><h2>{t.queue} <span>{queue.length}</span></h2><span>{bytes(queue.reduce((sum, e) => sum + e.bytes, 0))}</span></div>
                  {queue.map(episode => <article className="upload-episode" key={episode.recording}>
                    <div className={`upload-file-icon${episode.status === "complete" ? " is-complete" : ""}`}>{episode.status === "complete" ? <Check size={19} /> : <FolderUp size={19} />}</div>
                    <div className="upload-episode-content"><strong>{episode.recording}</strong><div className="upload-episode-meta"><span>{episode.files.length} {t.files} · {bytes(episode.bytes)}</span><span role="status">{t[episode.status]}</span></div>
                      {episode.status !== "ready" && <progress aria-label={episode.recording} max="100" value={episode.status === "complete" ? 100 : Math.min(99, episode.loaded / episode.bytes * 100)} />}
                    </div>
                    {!busy && episode.status === "ready" && <button className="upload-remove" aria-label={`${t.remove} ${episode.recording}`} onClick={() => setQueue(q => q.filter(e => e.recording !== episode.recording))}><X size={17} /></button>}
                  </article>)}
                  <div className="upload-actions">{busy ? <button className="upload-button upload-button--quiet" onClick={() => controller.current?.abort()}><Pause size={17} />{t.pause}</button> : !allDone && <button className="upload-button" onClick={start}><Upload size={17} />{queue.some(e => ["paused", "failed"].includes(e.status)) ? t.resume : t.start}</button>}
                    {!busy && <button className="upload-text-button" onClick={() => { setQueue([]); setError(""); }}>{t.clear}</button>}</div>
                </section>}
                {allDone && <section className="upload-success" role="status"><CheckCircle2 size={26} /><div><h2>{t.received}</h2><p>{t.next}</p></div></section>}
              </div>
              <aside className="upload-guidance"><h2>{t.heading}</h2><ol>{t.steps.map((step, i) => <li key={step}><span>{String(i + 1).padStart(2, "0")}</span><p>{step}</p></li>)}</ol>
                <div className="upload-allowance"><span className="upload-caption">{t.allowance}</span><strong>{bytes(info.remaining_bytes)}</strong></div>
                <p className="upload-caption">{t.private}</p>
              </aside>
            </div>
            {info.batches.length > 0 && <section className="upload-history"><h2>{t.history}</h2>{info.batches.slice(0, 8).map(b => <div key={b.id}><span>{b.recording}</span><span>{b.complete ? t.complete : t.incomplete}</span></div>)}</section>}
          </>}
        </main>
        <footer className="upload-footer"><span>6thSense · {t.eyebrow.toLowerCase()}</span><a href="mailto:alex@6thsense.dev">{t.contact} <ArrowUpRight size={15} /></a></footer>
      </div>
    </div>
  );
}
