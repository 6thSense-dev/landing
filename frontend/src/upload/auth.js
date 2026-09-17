// Cognito access tokens authorize the existing contributor API. No staff cookies
// or cloud credentials are used. Session storage is cleared on sign-out.
const API = import.meta.env?.VITE_API_URL ?? "";
const KEY = "6thsense-contributor-session";
let configuration;

export async function identityConfig() {
  if (!configuration) {
    const response = await fetch(`${API}/api/contributor/configuration`, { credentials: "omit", cache: "no-store" });
    if (!response.ok) throw Error("sign_in_unavailable");
    const data = await response.json();
    if (!/^[a-z]{2}-[a-z]+-\d$/.test(data.identity?.region) || !/^[a-z0-9]{10,128}$/i.test(data.identity?.clientId)) throw Error("sign_in_unavailable");
    configuration = data.identity;
  }
  return configuration;
}

export async function cognito(operation, payload) {
  const config = await identityConfig();
  const response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
    method: "POST", credentials: "omit", cache: "no-store",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${operation}` },
    body: JSON.stringify({ ClientId: config.clientId, ...payload }),
  });
  const data = await response.json();
  if (!response.ok) {
    // Provider bodies may contain personal information. Only expose a known code.
    const code = String(data.__type || "").split("#").pop();
    const known = ["NotAuthorizedException", "UserNotFoundException", "UserNotConfirmedException", "PasswordResetRequiredException", "TooManyRequestsException", "LimitExceededException", "CodeMismatchException", "ExpiredCodeException", "InvalidPasswordException"];
    throw Error(known.includes(code) ? code : "sign_in_unavailable");
  }
  return data;
}

export function phoneNumber(value) {
  const phone = value.replace(/[\s()-]/g, "");
  if (!/^\+[1-9]\d{7,14}$/.test(phone)) throw Error("phone_format");
  return phone;
}

export class ContributorSession {
  constructor(storage = globalThis.sessionStorage) {
    this.storage = storage; this.listeners = new Set(); this.generation = 0;
    try { this.tokens = JSON.parse(storage?.getItem(KEY) || "null"); } catch { this.tokens = null; }
  }
  get signedIn() { return Boolean(this.tokens?.refresh); }
  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  save(tokens) {
    this.tokens = tokens;
    try { if (tokens) this.storage?.setItem(KEY, JSON.stringify(tokens)); else this.storage?.removeItem(KEY); } catch { /* Memory-only session when storage is disabled. */ }
    this.listeners.forEach(listener => listener(this.signedIn));
  }
  async signIn(phone, password) {
    const data = await cognito("InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: phoneNumber(phone), PASSWORD: password } });
    if (!data.AuthenticationResult?.AccessToken || !data.AuthenticationResult?.RefreshToken) throw Error("account_setup_required");
    this.generation++;
    const r = data.AuthenticationResult;
    this.save({ access: r.AccessToken, refresh: r.RefreshToken, expires: Date.now() + r.ExpiresIn * 1000 });
  }
  async accessToken(force = false) {
    if (!this.signedIn) throw Error("authentication_required");
    if (!force && this.tokens.expires > Date.now() + 60000) return this.tokens.access;
    if (this.refreshing) return this.refreshing;
    const generation = this.generation, refresh = this.tokens.refresh;
    this.refreshing = (async () => {
      try {
        const data = await cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: refresh } });
        if (generation !== this.generation) throw Error("authentication_required");
        const r = data.AuthenticationResult;
        if (!r?.AccessToken) throw Error("NotAuthorizedException");
        this.save({ access: r.AccessToken, refresh: r.RefreshToken || refresh, expires: Date.now() + r.ExpiresIn * 1000 });
        return r.AccessToken;
      } catch (error) {
        if (generation === this.generation && error.message === "NotAuthorizedException") { this.generation++; this.save(null); }
        throw error;
      } finally { this.refreshing = null; }
    })();
    return this.refreshing;
  }
  async signOut() {
    const refresh = this.tokens?.refresh;
    this.generation++; this.save(null);
    if (refresh) await cognito("RevokeToken", { Token: refresh });
  }
}

let storage;
try { storage = globalThis.sessionStorage; } catch { storage = null; }
export const contributorSession = new ContributorSession(storage);
