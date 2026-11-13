// Thin client for studio/server.py. Same-origin only; the session cookie is HttpOnly.

export type Json = null | boolean | number | string | Json[] | {[k: string]: Json};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Any = any;

export class ApiError extends Error {
  status: number;
  code: string;
  detail: string | null;
  errors: string[];
  constructor(status: number, code: string, message: string, detail: string | null, errors: string[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.errors = errors;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {method, credentials: 'same-origin', headers: {Accept: 'application/json'}};
  if (body !== undefined) {
    init.headers = {...init.headers, 'Content-Type': 'application/json'};
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, 'NETWORK', 'The Studio server is not reachable (is it still running?)', String(e), []);
  }
  const text = await res.text();
  let data: Any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? `HTTP_${res.status}`, err.message ?? (text || res.statusText), err.detail ?? null, err.errors ?? []);
  }
  return data as T;
}

export const api = {
  get: <T = Any>(p: string) => call<T>('GET', p),
  post: <T = Any>(p: string, body: unknown = {}) => call<T>('POST', p, body),
  put: <T = Any>(p: string, body: unknown = {}) => call<T>('PUT', p, body),
};

/** URL for a workspace-relative file under output/ or public/ (served by safe_output_file). */
export const fileUrl = (rel: string | null | undefined, bust?: string | number) =>
  rel ? `/files/${rel.split('/').map(encodeURIComponent).join('/')}${bust !== undefined ? `?v=${encodeURIComponent(String(bust))}` : ''}` : '';

export const servable = (rel: string) => rel.startsWith('output/') || rel.startsWith('public/');

export type Task = {id: string; kind: string; production: string; status: 'running' | 'done' | 'failed';
  started_at: number; finished_at: number | null; result: Any; error: {code: string; message: string; detail?: string | null} | null};

/** Poll a background task until it finishes. */
export async function waitTask(id: string, onTick?: (t: Task) => void, intervalMs = 1200): Promise<Task> {
  for (;;) {
    const t = await api.get<Task>(`/api/tasks/${id}`);
    onTick?.(t);
    if (t.status !== 'running') return t;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
