import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groupEpisodes, droppedFiles, fingerprint } from '../src/upload/files.js';
import { ContributorSession, phoneNumber } from '../src/upload/auth.js';

const rec = 'ego_20260917_110000_ABC123';
const entry = (path, bytes = 'test') => ({ path: `SD/${rec}/${path}`, file: new File([bytes], path) });

test('whole folders group independently; hidden sidecars are ignored', () => {
  const result = groupEpisodes([entry('metadata.json'), entry('video.mp4'), entry('.DS_Store')]);
  assert.equal(result.episodes.length, 1); assert.equal(result.ignored, 1);
  assert.deepEqual(result.episodes[0].files.map(f => f.path), ['metadata.json', 'video.mp4']);
  assert.throws(() => groupEpisodes([entry('video.mp4')]), /metadata/);
  assert.throws(() => groupEpisodes([entry('metadata.json'), entry('video.mp4', '')]), /Empty/);
  assert.throws(() => groupEpisodes([entry('metadata.json'), entry('video.mp4'), entry('video.mp4')]), /Duplicate/);
  assert.throws(() => groupEpisodes([entry('metadata.json'), entry('bad name/video.mp4')]), /Unsupported/);
});

test('directory readers are drained beyond the first browser page', async () => {
  let count = 0;
  const child = name => ({ name, isFile: true, file: resolve => resolve(new File(['x'], name)) });
  const folder = { name: rec, isDirectory: true, createReader: () => ({ readEntries: resolve => {
    resolve(count++ < 2 ? Array.from({ length: 100 }, (_, i) => child(`${count}-${i}.mp4`)) : []);
  } }) };
  assert.equal((await droppedFiles([{ kind: 'file', webkitGetAsEntry: () => folder }])).length, 200);
  assert.notEqual(await fingerprint(new File(['a'], 'v')), await fingerprint(new File(['b'], 'v')));
});

test('phone sign-in uses international form', () => {
  assert.equal(phoneNumber('+82 (10) 1234-5678'), '+821012345678');
  assert.throws(() => phoneNumber('01012345678'), /phone_format/);
});

test('concurrent requests renew once; logout cannot resurrect a pending refresh', async () => {
  let renewals = 0, release;
  const memory = new Map();
  const storage = { getItem: k => memory.get(k), setItem: (k,v) => memory.set(k,v), removeItem: k => memory.delete(k) };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/configuration')) return Response.json({ identity: { region: 'us-west-2', clientId: 'testclient1234' } });
    const body = JSON.parse(init.body);
    if (body.Token) return Response.json({});
    if (body.AuthFlow === 'REFRESH_TOKEN_AUTH') { renewals++; if (release === 'wait') await new Promise(r => { release = r; }); }
    return Response.json({ AuthenticationResult: { AccessToken: 'access', RefreshToken: 'refresh', ExpiresIn: 900 } });
  };
  try {
    const session = new ContributorSession(storage);
    await session.signIn('+821012345678', 'sample-password');
    session.tokens.expires = 0;
    assert.deepEqual(await Promise.all([session.accessToken(), session.accessToken()]), ['access', 'access']);
    assert.equal(renewals, 1);
    session.tokens.expires = 0; release = 'wait';
    const pending = session.accessToken();
    while (typeof release !== 'function') await new Promise(r => setTimeout(r, 1));
    await session.signOut(); release();
    await assert.rejects(pending, /authentication_required/);
    assert.equal(session.signedIn, false); assert.equal(memory.size, 0);
  } finally { globalThis.fetch = originalFetch; }
});
