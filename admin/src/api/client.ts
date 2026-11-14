import type { AdminSession } from '@/types';

const baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? '';

/** Admin uploads come back as /media/... on our backend; make them absolute for <img>. */
export const mediaUrl = (url?: string | null) => (!url ? undefined : url.startsWith('/') ? `${env.apiBaseUrl}${url}` : url);

export const env = {
  /** Our backend (backend/), which talks to Salesforce. e.g. https://api.example.com */
  apiBaseUrl: baseUrl.replace(/\/+$/, ''),
  /** Demo data is used until a backend URL is set. */
  useMock: import.meta.env.VITE_USE_MOCK === 'true' || baseUrl === '',
  requestTimeoutMs: 20000,
};

// Kept in sessionStorage so closing the tab ends the admin session.
const SESSION_KEY = 'admin_session';
let currentToken: string | undefined;
let onUnauthorized: (() => void) | undefined;

export const sessionStore = {
  load(): AdminSession | undefined {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return undefined;
      const session = JSON.parse(raw) as AdminSession;
      currentToken = session.token;
      return session;
    } catch {
      return undefined;
    }
  },
  save(session: AdminSession) {
    currentToken = session.token;
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    } catch {
      // Storage unavailable (private mode): the session lives in memory only.
    }
  },
  clear() {
    currentToken = undefined;
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // ignore
    }
  },
};

/** Registered by the AuthProvider so an expired/revoked token logs the admin out. */
export function setUnauthorizedHandler(handler: (() => void) | undefined) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  /** Login is called without the bearer token. */
  auth?: boolean;
}

/** Thin fetch wrapper: base URL, bearer token, JSON, timeout and Salesforce error parsing. */
export async function request<T>(path: string, { method = 'GET', body, query, auth = true }: RequestOptions = {}): Promise<T> {
  const qs = query
    ? Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : '';

  const token = auth ? currentToken : undefined;
  const controller = new AbortController();
  const isUpload = body instanceof FormData;
  // Image uploads can be a few MB on a slow connection.
  const timer = setTimeout(() => controller.abort(), isUpload ? env.requestTimeoutMs * 3 : env.requestTimeoutMs);

  try {
    const res = await fetch(`${env.apiBaseUrl}${path}${qs ? `?${qs}` : ''}`, {
      method,
      headers: {
        Accept: 'application/json',
        // FormData sets its own multipart Content-Type (with the boundary).
        ...(isUpload ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : isUpload ? body : JSON.stringify(body),
      signal: controller.signal,
    });

    const text = await res.text();
    const data = text ? safeJson(text) : undefined;

    if (!res.ok) {
      if (res.status === 401 && token) onUnauthorized?.();
      throw new ApiError(extractSalesforceError(data) ?? `Request failed (${res.status})`, res.status);
    }
    return data as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === 'AbortError') throw new ApiError('Request timed out. Please try again.');
    throw new ApiError('Network error. Check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// Salesforce REST errors come back as [{ message, errorCode }] or { message }.
function extractSalesforceError(data: unknown): string | undefined {
  if (Array.isArray(data) && data[0]?.message) return String(data[0].message);
  if (data && typeof data === 'object' && 'message' in data) return String((data as { message: unknown }).message);
  return undefined;
}
