import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import type { LoginId } from '@/auth/loginId';

/** `data.type` of the push Salesforce sends once a registered broker has been added. */
export const PARTNER_ADDED = 'partner_added';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Returns this device's Expo push token, or undefined when notifications are off or unavailable
 * (Expo Go on Android, simulators, no EAS project id). Never throws: registration must still work.
 */
export async function getPushToken({ prompt }: { prompt: boolean }): Promise<string | undefined> {
  try {
    // Android 13+ only shows the permission prompt once a channel exists.
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Account updates',
        // Re-exported via `export *` from its types module, which eslint-plugin-import can't follow.
        // eslint-disable-next-line import/namespace
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted' && prompt) ({ status } = await Notifications.requestPermissionsAsync());
    if (status !== 'granted') return undefined;

    const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
    if (!projectId) return undefined;
    return (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  } catch {
    return undefined;
  }
}

export async function notificationsAllowed() {
  try {
    return (await Notifications.getPermissionsAsync()).status === 'granted';
  } catch {
    return false;
  }
}

/** Demo mode only: shows the "account ready" notification Salesforce would push. */
export async function showDemoPartnerAddedNotification(id: LoginId) {
  await getPushToken({ prompt: true });
  await Notifications.scheduleNotificationAsync({
    content: {
      title: 'Your account is ready',
      body: 'Ambuja Neotia has set up your Channel Partner account. Tap to log in.',
      data: { type: PARTNER_ADDED, ...id },
    },
    trigger: { type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL, seconds: 2 },
  });
}
