// Every backend (backend/) API the app talks to, one entry per API. The backend talks to Salesforce.
// Authenticated APIs scope every record to the broker behind the bearer token;
// the app never asks for another broker's data and never sends a broker id.

export const endpoints = {
  // Auth (public — no bearer token)
  checkMobile: () => `/auth/check-mobile`,
  checkEmail: () => `/auth/check-email`,
  requestOtp: () => `/auth/otp/request`,
  verifyOtp: () => `/auth/otp/verify`,
  passwordLogin: () => `/auth/password-login`,
  setPassword: () => `/auth/password`,
  registerBroker: () => `/auth/register`,
  accountForm: () => `/auth/account-form`,
  logout: () => `/auth/logout`,

  // Dashboard
  dashboardSummary: () => `/dashboard/summary`,

  // Enquiries
  listEnquiries: () => `/enquiries`,
  getEnquiry: (id: string) => `/enquiries/${encodeURIComponent(id)}`,
  getEnquiryStatusHistory: (id: string) => `/enquiries/${encodeURIComponent(id)}/status-history`,
  createEnquiry: () => `/enquiries`,
  leadForm: () => `/lead-form`,

  // Projects / Brochures
  listProjects: () => `/projects`,
  getProject: (id: string) => `/projects/${encodeURIComponent(id)}`,

  // Profile
  getProfile: () => `/me`,
} as const;
