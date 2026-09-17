import { fingerprint } from "./files.js";

const API = import.meta.env.VITE_API_URL ?? "";
const paused = () => new DOMException("Upload paused", "AbortError");
function check(signal) { if (signal?.aborted) throw paused(); }

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    check(signal);
    const cancel = () => { clearTimeout(timer); reject(paused()); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", cancel); resolve(); }, ms);
    signal?.addEventListener("abort", cancel, { once: true });
  });
}

export async function uploadApi(session, path, body, signal) {
  let renewed = false;
  for (let attempt = 0; ; attempt++) {
    check(signal);
    const token = await session.accessToken();
    check(signal);
    let response;
    try {
      response = await fetch(`${API}/api/uploads${path}`, {
        method: body === undefined ? "GET" : "POST", credentials: "omit", signal,
        headers: { Authorization: `Bearer ${token}`, ...(body !== undefined && { "Content-Type": "application/json" }) },
        ...(body !== undefined && { body: JSON.stringify(body) }),
      });
    } catch (error) {
      if (signal?.aborted) throw paused();
      if (attempt >= 3) throw Error("Connection interrupted. Retry to resume your upload.");
      await delay(1000 * 2 ** attempt, signal); continue;
    }
    if (response.status === 401 && !renewed) {
      renewed = true; await session.accessToken(true); continue;
    }
    if ((response.status >= 500 || response.status === 429) && attempt < 3) {
      await delay(1000 * 2 ** attempt, signal); continue;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(result.detail) ? result.detail[0]?.msg : result.detail;
      throw Error(detail || `Upload request failed (${response.status}). Please retry.`);
    }
    return result;
  }
}

function putPart(url, blob, checksum, progress, signal) {
  return new Promise((resolve, reject) => {
    check(signal);
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const finish = (fn, value) => { signal.removeEventListener("abort", abort); fn(value); };
    xhr.open("PUT", url);
    xhr.timeout = 180000;
    xhr.setRequestHeader("x-amz-checksum-sha256", checksum);
    xhr.upload.onprogress = event => progress(event.loaded);
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) finish(resolve, etag);
      else finish(reject, Error("The file part could not be verified. Retry to resume."));
    };
    xhr.onerror = xhr.ontimeout = () => finish(reject, Error("Transfer interrupted. Retry to resume."));
    xhr.onabort = () => finish(reject, paused());
    signal.addEventListener("abort", abort, { once: true });
    xhr.send(blob);
  });
}

async function sendPart(part, blob, progress, signal) {
  for (let attempt = 0; ; attempt++) {
    try { return await putPart(part.url, blob, part.checksum, progress, signal); }
    catch (error) {
      if (signal.aborted || attempt >= 2) throw error;
      progress(0);
      await delay(1000 * 2 ** attempt, signal);
    }
  }
}

async function transferFile(token, batch, remote, file, onProgress, signal) {
  const path = `/batches/${batch.id}/files/${remote.id}`;
  const started = await uploadApi(token, `${path}/start`, {}, signal);
  if (started.complete) { onProgress(file.size); return; }
  const size = started.part_bytes;
  const count = Math.ceil(file.size / size);
  const partSize = n => Math.min(size, file.size - (n - 1) * size);
  const received = new Map(started.received.map(p => [p.number, p]));
  const loaded = new Map([...received.keys()].map(n => [n, partSize(n)]));
  const report = () => { if (!signal.aborted) onProgress([...loaded.values()].reduce((a, b) => a + b, 0)); };
  report();
  let pending = [];
  const missing = Array.from({ length: count }, (_, i) => i + 1).filter(n => !received.has(n));
  for (let offset = 0; offset < missing.length; offset += 3) {
    check(signal);
    const group = await Promise.all(missing.slice(offset, offset + 3).map(async number => {
      const blob = file.slice((number - 1) * size, number * size);
      const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
      return { number, blob, checksum: btoa(String.fromCharCode(...hash)) };
    }));
    const signed = await uploadApi(token, `${path}/parts`, {
      parts: group.map(({ number, checksum }) => ({ number, checksum })), received: pending,
    }, signal);
    pending = [];
    if (signed.complete) { onProgress(file.size); return; }
    pending = await Promise.all(signed.parts.map(async part => {
      const blob = group.find(g => g.number === part.number).blob;
      const etag = part.etag || await sendPart(part, blob, value => { loaded.set(part.number, value); report(); }, signal);
      loaded.set(part.number, blob.size); report();
      return { number: part.number, etag };
    }));
  }
  await uploadApi(token, `${path}/complete`, { received: pending }, signal);
  onProgress(file.size);
}

export async function transferEpisode(token, episode, onProgress, signal) {
  const manifest = [];
  for (const { file, path } of episode.files) {
    check(signal);
    manifest.push({ path, size: file.size, modified_ms: file.lastModified, fingerprint: await fingerprint(file) });
  }
  const batch = await uploadApi(token, "/batches", { recording: episode.recording, files: manifest }, signal);
  if (batch.complete) { onProgress(episode.bytes); return batch; }
  let finished = 0;
  for (const remote of batch.files) {
    const local = episode.files.find(f => f.path === remote.path);
    if (!local || local.file.size !== remote.size) throw Error("Select the original episode folder to resume.");
    await transferFile(token, batch, remote, local.file, value => onProgress(finished + value), signal);
    finished += local.file.size;
  }
  return uploadApi(token, `/batches/${batch.id}/complete`, {}, signal);
}
