import * as Notifications from 'expo-notifications';
import { Stack, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { Loading } from '@/components/ui';
import { PARTNER_ADDED } from '@/notifications/push';
import { colors } from '@/theme';
import { loginIdFromParams, loginIdParams } from '@/auth/loginId';

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <RootStack />
    </AuthProvider>
  );
}

/** Tapping the "account ready" push (sent by the backend) opens login with the mobile (or email) checked. */
function useAccountReadyTaps(enabled: boolean) {
  const router = useRouter();
  const response = Notifications.useLastNotificationResponse();
  useEffect(() => {
    if (!enabled || !response || response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const data = response.notification.request.content.data as { type?: string; mobile?: string; email?: string } | undefined;
    const id = data?.type === PARTNER_ADDED ? loginIdFromParams(data) : undefined;
    if (!id) return;
    router.replace({ pathname: '/login', params: { ...loginIdParams(id), check: '1' } });
    void Notifications.clearLastNotificationResponseAsync();
  }, [enabled, response, router]);
}

function RootStack() {
  const { restoring, session } = useAuth();
  const loggedIn = !!session;
  useAccountReadyTaps(!restoring && !loggedIn);
  if (restoring) return <Loading />;

  return (
    <Stack
      screenOptions={{
        headerTransparent: false,
        headerStyle: { backgroundColor: colors.bg },
        headerShadowVisible: false,
        headerTintColor: colors.primary,
        headerTitleStyle: { color: colors.text, fontWeight: '700' },
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: colors.bg },
      }}
    >
      <Stack.Protected guard={loggedIn} redirectTo="/login">
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="enquiries/new" options={{ title: 'Create Lead', presentation: 'modal' }} />
        <Stack.Screen name="enquiries/[id]" options={{ title: 'Lead' }} />
        <Stack.Screen name="projects/[id]" options={{ title: 'Project' }} />
        <Stack.Screen name="password" options={{ title: 'Password' }} />
      </Stack.Protected>

      <Stack.Protected guard={!loggedIn} redirectTo="/">
        <Stack.Screen name="login" options={{ headerShown: false }} />
        <Stack.Screen name="register" options={{ title: 'Register as Channel Partner' }} />
        <Stack.Screen name="pending" options={{ headerShown: false }} />
      </Stack.Protected>
    </Stack>
  );
}
