/**
 * Thin fetch wrapper.
 *
 * Session cookies do the authentication, so every request sends credentials and
 * every unsafe request carries the CSRF token Django issued.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** US-02.2 AC2 - the fields that are blocking submission, if any. */
  get missingFields(): string[] {
    const body = this.body as { missing_fields?: string[] } | null;
    return body?.missing_fields ?? [];
  }
}

export function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[2]) : null;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (UNSAFE.has(method)) {
    const token = readCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }

  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      (payload as { detail?: string } | null)?.detail ?? "Something went wrong.";
    throw new ApiError(response.status, payload, detail);
  }
  return payload as T;
}

/** Called once on start-up so that the CSRF cookie exists before any POST. */
export function primeCsrf(): Promise<unknown> {
  return request("/api/auth/csrf/");
}
