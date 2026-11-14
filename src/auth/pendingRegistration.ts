import * as SecureStore from 'expo-secure-store';
import { parseLoginId, serializeLoginId, type LoginId } from './loginId';

// The mobile or email of a registration awaiting approval, so reopening the app goes straight
// back to its status instead of asking again. The key name predates mobile login; kept so a
// pending registration saved by an older version is still found.
const KEY = 'pending_registration_email';

export const pendingRegistration = {
  async get(): Promise<LoginId | undefined> {
    try {
      const value = await SecureStore.getItemAsync(KEY);
      return value ? parseLoginId(value) : undefined;
    } catch {
      return undefined;
    }
  },
  async set(id: LoginId) {
    await SecureStore.setItemAsync(KEY, serializeLoginId(id)).catch(() => {});
  },
  async clear() {
    await SecureStore.deleteItemAsync(KEY).catch(() => {});
  },
};
