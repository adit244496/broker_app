// How a broker identifies themselves at login: the mobile number on their Channel Partner account
// (code by SMS) or its email (code by email). Mobile is the default; email is the fallback.

export type LoginId = { mobile: string } | { email: string };

export const isMobileId = (id: LoginId): id is { mobile: string } => 'mobile' in id;

/** Digits only, last 10: accepts "+91 98300 12345" or "098300 12345". */
export const normalizeMobile = (value: string) => value.replace(/\D/g, '').slice(-10);

export const normalizeEmail = (value: string) => value.trim().toLowerCase();

/** As shown to the broker, e.g. "+91 9830012345". */
export const describeLoginId = (id: LoginId) => (isMobileId(id) ? `+91 ${id.mobile}` : id.email);

/** Route params for screens that take a login id (`?mobile=` or `?email=`). */
export const loginIdParams = (id: LoginId): Record<string, string> => ({ ...id });

export function loginIdFromParams(params: { mobile?: string; email?: string }): LoginId | undefined {
  if (params.mobile) return { mobile: normalizeMobile(params.mobile) };
  if (params.email) return { email: normalizeEmail(params.email) };
  return undefined;
}

/** Stored as the bare value: 10 digits is a mobile, anything else an email (older app versions stored emails). */
export const serializeLoginId = (id: LoginId) => (isMobileId(id) ? id.mobile : id.email);

export const parseLoginId = (value: string): LoginId =>
  /^\d{10}$/.test(value) ? { mobile: value } : { email: normalizeEmail(value) };
