// Thin JSON client for the loopback API. The session lives in an HttpOnly cookie; the CSRF token
// is kept in memory only (never localStorage/sessionStorage) and sent on every write.

export class ApiFailure extends Error {
  constructor(
    public status: number,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

let csrf = "";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers:
        method === "GET"
          ? {}
          : { "Content-Type": "application/json", "X-OHG-CSRF": csrf },
      body: body === undefined ? (method === "GET" ? undefined : "{}") : JSON.stringify(body),
    });
  } catch {
    throw new ApiFailure(0, "Can't reach OpenHypergamy. Is `ohg onboard` still running?");
  }
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    throw new ApiFailure(
      res.status,
      typeof data.error === "string" ? data.error : `Request failed (${res.status}).`,
      (data.fields as Record<string, string>) ?? {},
    );
  }
  return data as T;
}

export const api = {
  async connect(): Promise<void> {
    csrf = (await call<{ csrf: string }>("GET", "/api/session")).csrf;
  },
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => call<T>("PUT", path, body),
};
