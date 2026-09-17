import { test, expect } from '@playwright/test';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

const recording = 'ego_20260917_110000_ABC123';
const etag = '"' + 'a'.repeat(32) + '"';

async function mock(page, { approved = true, signedIn = false } = {}) {
  if (signedIn) await page.addInitScript(() => sessionStorage.setItem('6thsense-contributor-session', JSON.stringify({ access: 'test-access', refresh: 'test-refresh', expires: Date.now() + 900000 })));
  await page.route('**/api/contributor/configuration', r => r.fulfill({ json: { identity: { region: 'us-west-2', clientId: 'testclient1234' } } }));
  await page.route('https://cognito-idp.us-west-2.amazonaws.com/**', r => r.fulfill({ json: r.request().postDataJSON().Token ? {} : { AuthenticationResult: { AccessToken: 'test-access', RefreshToken: 'test-refresh', ExpiresIn: 900 } } }));
  const files = [], received = new Map();
  let complete = false, partCount = 0;
  await page.route('**/api/uploads/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    expect(req.headers().authorization).toBe('Bearer test-access');
    if (!approved) return route.fulfill({ status: 403, json: { detail: 'camera_approval_required' } });
    if (path.endsWith('/info')) return route.fulfill({ json: { name: 'Test Contributor', remaining_bytes: 500*1024**3, batches: complete ? [{ id: 'batch', recording, complete: true }] : [] } });
    if (path.endsWith('/batches')) {
      if (!files.length) for (const [i, f] of req.postDataJSON().files.entries()) files.push({ ...f, id: `file${i}`, complete: false });
      return route.fulfill({ json: { id: 'batch', recording, files, complete: false } });
    }
    if (path.endsWith('/start')) return route.fulfill({ json: { complete: false, part_bytes: 16*1024**2, received: [] } });
    if (path.endsWith('/parts')) {
      const file = path.split('/').at(-2), body = req.postDataJSON();
      return route.fulfill({ json: { parts: body.parts.map(p => {
        received.set(`${file}/${p.number}`, p.checksum);
        return { ...p, url: `https://test-upload.invalid/${file}/${p.number}` };
      }) } });
    }
    if (path.includes('/files/') && path.endsWith('/complete')) {
      expect(req.postDataJSON().received.every(p => p.etag === etag)).toBeTruthy();
      return route.fulfill({ json: { complete: true } });
    }
    complete = true; return route.fulfill({ json: { complete: true, recording } });
  });
  await page.route('https://test-upload.invalid/**', async route => {
    const req = route.request();
    if (req.method() === 'OPTIONS') return route.fulfill({ headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'PUT', 'Access-Control-Allow-Headers': '*' } });
    const hash = createHash('sha256').update(req.postDataBuffer()).digest('base64');
    expect(req.headers()['x-amz-checksum-sha256']).toBe(hash);
    expect(received.get(new URL(req.url()).pathname.slice(1))).toBe(hash);
    partCount++;
    return route.fulfill({ status: 200, headers: { ETag: etag, 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'ETag' } });
  });
  return { parts: () => partCount };
}

test('account sign-in, complete folder transfer, receipt, sign-out', async ({ page }, testInfo) => {
  const server = await mock(page);
  await page.goto('/upload');
  await expect(page.getByRole('heading', { name: 'Sign in to upload' })).toBeVisible();
  await page.getByLabel('Phone number', { exact: false }).fill('+821012345678');
  await page.getByLabel('Password', { exact: true }).fill('ExamplePassword1');
  await page.getByRole('button', { name: 'Sign in to upload' }).click();
  await expect(page.getByText('Test Contributor', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('upload-ready.png'), fullPage: true });
  const root = await mkdtemp(join(tmpdir(), 'upload-e2e-'));
  try {
    const folder = join(root, recording); await mkdir(folder);
    await writeFile(join(folder, 'metadata.json'), JSON.stringify({ device_id: 'ABC123' }));
    await writeFile(join(folder, 'video.mp4'), Buffer.alloc(16*1024**2 + 10, 1));
    await page.locator('input[type=file]').setInputFiles(folder);
    await page.getByRole('button', { name: 'Upload episodes', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Episodes received. Thank you.' })).toBeVisible();
    expect(server.parts()).toBe(3);
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Sign in to upload' })).toBeVisible();
    expect(await page.evaluate(() => sessionStorage.getItem('6thsense-contributor-session'))).toBeNull();
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('unapproved contributors see next step and cannot choose files', async ({ page }) => {
  await mock(page, { approved: false, signedIn: true });
  await page.goto('/upload');
  await expect(page.getByRole('heading', { name: /camera assignment is waiting/ })).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  await page.getByRole('button', { name: '한국어' }).click();
  await expect(page.getByRole('heading', { name: /카메라 배정 승인/ })).toBeVisible();
});

test('password reset sends a code and returns to sign-in', async ({ page }) => {
  await mock(page);
  const operations = [];
  await page.route('https://cognito-idp.us-west-2.amazonaws.com/**', route => {
    operations.push({ operation: route.request().headers()['x-amz-target'].split('.').pop(), body: route.request().postDataJSON() });
    return route.fulfill({ json: {} });
  });
  await page.goto('/upload');
  await page.getByRole('button', { name: 'Forgot password?' }).click();
  await page.getByLabel('Phone number', { exact: false }).fill('+821012345678');
  await page.getByRole('button', { name: 'Send reset code' }).click();
  await expect(page.getByLabel('Verification code')).toBeVisible();
  await page.getByLabel('Verification code').fill('123456');
  await page.getByLabel('New password', { exact: false }).fill('ChangedPassword1');
  await page.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(page.getByText('Password updated. You can now sign in.')).toBeVisible();
  expect(operations.map(o => o.operation)).toEqual(['ForgotPassword', 'ConfirmForgotPassword']);
  expect(operations[1].body.Username).toBe('+821012345678');
  expect(operations[1].body.ConfirmationCode).toBe('123456');
});

test('pausing an in-flight part keeps the selected folder resumable', async ({ page }) => {
  await mock(page, { signedIn: true });
  let held;
  const hold = async route => {
    if (route.request().method() === 'PUT') { held = route; return; }
    return route.fallback();
  };
  await page.route('https://test-upload.invalid/**', hold);
  await page.goto('/upload');
  const root = await mkdtemp(join(tmpdir(), 'upload-pause-e2e-'));
  try {
    const folder = join(root, recording); await mkdir(folder);
    await writeFile(join(folder, 'metadata.json'), '{}');
    await writeFile(join(folder, 'video.mp4'), 'sample');
    await page.locator('input[type=file]').setInputFiles(folder);
    await page.getByRole('button', { name: 'Upload episodes', exact: true }).click();
    await expect.poll(() => Boolean(held)).toBe(true);
    await page.getByRole('button', { name: 'Pause', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Resume upload' })).toBeVisible();
    await held.abort().catch(() => {});
    await page.unroute('https://test-upload.invalid/**', hold);
    await page.getByRole('button', { name: 'Resume upload' }).click();
    await expect(page.getByRole('heading', { name: 'Episodes received. Thank you.' })).toBeVisible();
  } finally { await rm(root, { recursive: true, force: true }); }
});
