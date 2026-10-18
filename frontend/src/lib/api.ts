export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** JSON request to the backend through the dev proxy (same origin, so the session cookie rides along). */
export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: init?.method ?? (init?.body !== undefined ? "POST" : "GET"),
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const message = Array.isArray(detail?.detail)
      ? detail.detail.map((d: { msg: string }) => d.msg).join(", ")
      : (detail?.detail ?? response.statusText);
    throw new ApiError(response.status, String(message));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}
