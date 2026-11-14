// Runtime configuration. Set these in a `.env` file (see .env.example).
// EXPO_PUBLIC_* variables are inlined at build time by Expo.

const baseUrl = process.env.EXPO_PUBLIC_API_BASE_URL ?? '';

export const env = {
  /** Our backend (backend/), which talks to Salesforce. e.g. https://api.example.com */
  apiBaseUrl: baseUrl.replace(/\/+$/, ''),
  /** Demo data is used until a backend URL is set. */
  useMock: process.env.EXPO_PUBLIC_USE_MOCK === 'true' || baseUrl === '',
  requestTimeoutMs: 20000,
};
