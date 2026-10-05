const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_KEY = "BOL_access_token";
const REFRESH_KEY = "BOL_refresh_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string) {
  window.localStorage.setItem(ACCESS_KEY, access);
  window.localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  const res = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    clearTokens();
    return null;
  }
  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return data.access_token as string;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  query?: Record<string, string | number | undefined>;
}

function buildQuery(query?: Record<string, string | number | undefined>): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// Shared 401-refresh-and-retry so apiRequest and apiUpload (multipart, which
// can't share apiRequest's JSON-only body handling) don't duplicate the
// refresh-token dance.
async function fetchWithAuthRetry(
  fullPath: string,
  auth: boolean,
  buildInit: (token: string | null) => RequestInit,
): Promise<Response> {
  let token = auth ? getAccessToken() : null;
  let res = await fetch(`${API_URL}${fullPath}`, buildInit(token));

  if (auth && res.status === 401) {
    token = await refreshAccessToken();
    if (token) {
      res = await fetch(`${API_URL}${fullPath}`, buildInit(token));
    }
  }
  return res;
}

async function parseResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      // ignore body parse failure
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, query } = options;
  const fullPath = `${path}${buildQuery(query)}`;

  const res = await fetchWithAuthRetry(fullPath, auth, (token) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    return {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    };
  });

  return parseResponse<T>(res);
}

// For multipart uploads (e.g. ambience clips) — no Content-Type header, the
// browser sets it (with the multipart boundary) from the FormData itself.
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetchWithAuthRetry(path, true, (token) => {
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return { method: "POST", headers, body: formData };
  });

  return parseResponse<T>(res);
}
