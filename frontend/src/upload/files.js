const RECORDING = /^ego_\d{8}_\d{6}_[0-9A-Za-z]{4,8}(?:_[A-Za-z0-9]+)?$/;
const MEDIA = /\.(mp4|mov|m4v|webm|egoc)$/i;
const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;

export async function droppedFiles(items) {
  const output = [];
  async function walk(entry, parent = "") {
    if (entry.name.startsWith(".") || entry.name.startsWith("_")) return;
    const path = parent + entry.name;
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      output.push({ file, path });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      while (true) {
        const entries = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!entries.length) break;
        for (const child of entries) await walk(child, path + "/");
      }
    }
  }
  // Read DataTransfer entries while the drop event still owns its file handles.
  const entries = Array.from(items).filter(i => i.kind === "file").map(i => i.webkitGetAsEntry?.());
  if (!entries.length || entries.some(e => !e)) throw Error("Use Choose folders to select the original episode folder.");
  for (const entry of entries) await walk(entry);
  return output;
}

export function groupEpisodes(input) {
  const groups = new Map();
  let ignored = 0;
  for (const { file, path } of input) {
    const pieces = path.split("/");
    if (pieces.some(p => p.startsWith(".") || p.startsWith("_"))) { ignored++; continue; }
    const root = pieces.findIndex(p => RECORDING.test(p));
    if (root < 0 || root === pieces.length - 1) { ignored++; continue; }
    const recording = pieces[root];
    const tail = pieces.slice(root + 1);
    if (tail.length > 5 || tail.some(p => !SEGMENT.test(p))) throw Error(`Unsupported filename: ${path}`);
    if (!file.size) throw Error(`Empty file: ${path}. Finish recording before uploading.`);
    if (file.size > 100 * 1024 ** 3) throw Error(`${file.name} exceeds 100 GiB.`);
    const group = groups.get(recording) || { recording, files: [], bytes: 0 };
    const relative = tail.join("/");
    if (group.files.some(f => f.path === relative)) throw Error(`Duplicate file in ${recording}: ${relative}`);
    group.files.push({ file, path: relative });
    group.bytes += file.size;
    groups.set(recording, group);
  }
  if (!groups.size) throw Error("Choose an original ego_… episode folder containing metadata.json and recording files.");
  for (const group of groups.values()) {
    if (!group.files.some(f => f.path === "metadata.json") || !group.files.some(f => MEDIA.test(f.path))) {
      throw Error(`${group.recording}: include metadata.json and the original recording files.`);
    }
    if (group.files.length > 2000 || group.bytes > 500 * 1024 ** 3) throw Error(`${group.recording} exceeds the episode upload limit.`);
    group.files.sort((a, b) => a.path.localeCompare(b.path));
  }
  return { episodes: [...groups.values()].sort((a, b) => a.recording.localeCompare(b.recording)), ignored };
}

export async function fingerprint(file) {
  const sample = new Blob([file.slice(0, 1024 ** 2), file.slice(Math.max(0, file.size - 1024 ** 2))]);
  const digest = await crypto.subtle.digest("SHA-256", await sample.arrayBuffer());
  return [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, "0")).join("");
}

export function bytes(value = 0) {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.ceil(value / 1024)} KB`;
}
