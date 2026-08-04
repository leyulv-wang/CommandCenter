const SAFE_HEADER_NAMES = new Map([
  ['content-type', 'Content-Type'],
]);

const CREDENTIAL_HEADER_NAMES = new Set([
  'authorization',
  'proxy-authorization',
  'cookie',
  'set-cookie',
  'x-access-token',
  'x-api-key',
  'api-key',
  'apikey',
]);

const encoder = new TextEncoder();

export function isCredentialHeader(name) {
  const normalized = String(name ?? '').trim().toLowerCase();
  return CREDENTIAL_HEADER_NAMES.has(normalized)
    || normalized.endsWith('-api-key')
    || normalized.endsWith('-apikey');
}

export function sanitizeHeaders(headers = {}) {
  const sanitized = {};
  for (const [name, value] of Object.entries(headers ?? {})) {
    const normalized = name.trim().toLowerCase();
    const safeName = SAFE_HEADER_NAMES.get(normalized);
    if (!safeName || isCredentialHeader(normalized) || typeof value !== 'string') continue;
    sanitized[safeName] = value.trim().slice(0, 128);
  }
  return sanitized;
}

export function sanitizeUrl(value) {
  const url = new URL(value);
  const queryParameterNames = [];
  const seen = new Set();
  for (const rawName of url.searchParams.keys()) {
    const name = rawName.slice(0, 128);
    if (/^[A-Za-z][A-Za-z0-9_.-]*$/.test(name) && !seen.has(name)) {
      seen.add(name);
      queryParameterNames.push(name);
    }
  }
  return { origin: url.origin, path: url.pathname || '/', queryParameterNames };
}

export function summarizeBody(value, byteLimit = 64 * 1024) {
  const raw = typeof value === 'string' ? value : '';
  const byteLength = encoder.encode(raw).byteLength;
  const marker = raw ? '[body omitted]' : '';
  let json = false;
  if (raw && byteLength <= byteLimit) {
    try {
      JSON.parse(raw);
      json = true;
    } catch {
      // Invalid or non-JSON bodies are never retained.
    }
  }
  return {
    body: marker.slice(0, Math.max(0, byteLimit)),
    byteLength,
    json,
    truncated: byteLength > byteLimit,
  };
}

function bytesToHex(bytes) {
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function hmacFingerprint(value, key) {
  if (typeof key !== 'string' || key.length === 0) throw new TypeError('A non-empty HMAC key is required.');
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    encoder.encode(key),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', cryptoKey, encoder.encode(String(value ?? '')));
  return `hmac-sha256:${bytesToHex(signature)}`;
}
