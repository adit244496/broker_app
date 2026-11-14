import type { ConfigContext, ExpoConfig } from 'expo/config';

// Extends app.json. While the backend is reached over plain HTTP (an IP address, before the domain and its
// HTTPS certificate exist), Android release builds must be allowed cleartext traffic or every API call fails.
// Once EXPO_PUBLIC_API_BASE_URL is https://, this turns itself off.
const apiUrl = process.env.EXPO_PUBLIC_API_BASE_URL ?? '';
const allowHttp = apiUrl.startsWith('http://');

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...(config as ExpoConfig),
  plugins: [
    ...(config.plugins ?? []),
    ['expo-build-properties', { android: { usesCleartextTraffic: allowHttp } }],
  ],
});
