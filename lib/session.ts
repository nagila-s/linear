/**
 * Sessao HMAC com Web Crypto (compativel com Edge middleware e Node).
 */

const SESSION_TTL_SECONDS = 60 * 60 * 24;
const textEncoder = new TextEncoder();

function getSessionSecret(): string {
  const secret =
    process.env.SESSION_SECRET?.trim() ||
    process.env.ACCESS_PASSWORD?.trim() ||
    process.env.APP_PASSWORD?.trim() ||
    "";
  if (!secret) {
    throw new Error("SESSION_SECRET (ou ACCESS_PASSWORD) nao configurada.");
  }
  return secret;
}

function bytesToBase64Url(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (let i = 0; i < view.length; i++) binary += String.fromCharCode(view[i]!);
  const b64 = btoa(binary);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

async function importHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    textEncoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

async function sign(payloadB64: string): Promise<string> {
  const key = await importHmacKey(getSessionSecret());
  const signature = await crypto.subtle.sign("HMAC", key, textEncoder.encode(payloadB64));
  return bytesToBase64Url(signature);
}

export type SessionPayload = {
  sub: string;
  iat: number;
  exp: number;
};

export async function createSignedSessionToken(subject = "linear-user"): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const payload: SessionPayload = {
    sub: subject,
    iat: now,
    exp: now + SESSION_TTL_SECONDS,
  };
  const payloadB64 = bytesToBase64Url(textEncoder.encode(JSON.stringify(payload)));
  const signature = await sign(payloadB64);
  return `${payloadB64}.${signature}`;
}

export async function verifySignedSessionToken(
  token: string | undefined | null,
): Promise<SessionPayload | null> {
  if (!token || !token.includes(".")) return null;
  const [payloadB64, signature] = token.split(".");
  if (!payloadB64 || !signature) return null;

  let key: CryptoKey;
  try {
    key = await importHmacKey(getSessionSecret());
  } catch {
    return null;
  }

  const expected = await crypto.subtle.sign("HMAC", key, textEncoder.encode(payloadB64));
  const expectedB64 = bytesToBase64Url(expected);
  if (expectedB64.length !== signature.length) return null;

  // Comparacao em tempo constante simples
  let diff = 0;
  for (let i = 0; i < expectedB64.length; i++) {
    diff |= expectedB64.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  if (diff !== 0) return null;

  try {
    const json = new TextDecoder().decode(base64UrlToBytes(payloadB64));
    const payload = JSON.parse(json) as SessionPayload;
    if (!payload.exp || payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}
