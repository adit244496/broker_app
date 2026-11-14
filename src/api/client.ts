import * as SecureStore from 'expo-secure-store';
import { env } from '@/config/env';

import type { Session } from '@/types/models';

const SESSION_KEY = 'broker_session';

let currentToken: string | undefined;
let onUnauthorized: (() => void) | undefined;

/** Persists the session in the device keychain/keystore and keeps the token in memory for requests. */
export const sessionStore = {
  async load(): Promise<Session | undefined> {
    const raw = await SecureStore.getItemAsync(SESSION_KEY);
    if (!raw) return undefined;
    try {
      const session = JSON.parse(raw) as Session;
      currentToken = session.token;
      return session;
    } catch {
      await SecureStore.deleteItemAsync(SESSION_KEY);
      return undefined;
    }
  },
  async save(session: Session) {
    currentToken = session.token;
    await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
  },
  async clear() {
    currentToken = undefined;
    await SecureStore.deleteItemAsync(SESSION_KEY);
  },
};

/** Registered by the AuthProvider so an expired/revoked token logs the user out. */
export function setUnauthorizedHandler(handler: (() => void) | undefined) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  /** Public endpoints (login, registration) are called without the bearer token. */
  auth?: boolean;
}

/** Thin fetch wrapper: base URL, bearer token, JSON, timeout and Salesforce error parsing. */
export async function request<T>(path: string, { method = 'GET', body, query, auth = true }: RequestOptions = {}): Promise<T> {
  const qs = query
    ? '?' +
      Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : '';

  const token = auth ? currentToken : undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), env.requestTimeoutMs);

  try {
    const res = await fetch(`${env.apiBaseUrl}${path}${qs}`, {
      method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });

    const text = await res.text();
    const data = text ? safeJson(text) : undefined;

    if (!res.ok) {
      if (res.status === 401 && token) onUnauthorized?.();
      throw new ApiError(extractSalesforceError(data) ?? `Request failed (${res.status})`, res.status, data);
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
