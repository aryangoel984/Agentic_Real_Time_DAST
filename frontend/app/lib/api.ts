// Tiny API helper. Every call goes to the same origin (/api/...), which
// Next.js forwards to the FastAPI backend. Returns the raw status and body
// so the UI can show exactly what the server answered.

export type ApiResult = {
  method: string;
  path: string;
  status: number;
  ok: boolean;
  data: unknown;
  ms: number;
};

const TOKEN_KEY = "travelhub_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export async function apiRequest(
  method: string,
  path: string,
  body?: unknown,
  opts: { withToken?: boolean } = {},
): Promise<ApiResult> {
  const withToken = opts.withToken ?? true;
  const token = withToken ? getToken() : null;
  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    return { method, path, status: 0, ok: false, ms: 0,
      data: { error: "Could not reach the portal server." } };
  }
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.status >= 500) data = { error: "Backend not reachable. Is it running on port 8000?" };
  }
  return { method, path, status: res.status, ok: res.ok, data,
    ms: Math.round(performance.now() - started) };
}

export function inr(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
