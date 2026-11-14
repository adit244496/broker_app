import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppState, Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { mock } from '@/api/mock/mockData';
import { authApi } from '@/api/services';
import { describeLoginId, isMobileId, loginIdFromParams, loginIdParams } from '@/auth/loginId';
import { pendingRegistration } from '@/auth/pendingRegistration';
import { BrandLogo, Button, Card } from '@/components/ui';
import { env } from '@/config/env';
import { getPushToken, notificationsAllowed, showDemoPartnerAddedNotification } from '@/notifications/push';
import { colors, radius, spacing } from '@/theme';
import type { PendingStage } from '@/types/models';

type StepState = 'done' | 'current' | 'upcoming';

/**
 * Shown from registration until Salesforce reports the broker as added. Re-checks the status
 * whenever the app comes to the foreground; any non-pending result goes back to login.
 */
export default function PendingScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ mobile?: string; email?: string }>();
  // Memoised on the raw params so `check` keeps a stable identity between renders.
  const id = useMemo(() => loginIdFromParams({ mobile: params.mobile, email: params.email }), [params.mobile, params.email]);
  const [stage, setStage] = useState<PendingStage>();
  const [accountName, setAccountName] = useState<string>();
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string>();
  const [notifyOn, setNotifyOn] = useState<boolean>();

  const check = useCallback(async () => {
    if (!id) return;
    // Sends the current push token so Salesforce can still notify a reinstalled app.
    const token = await getPushToken({ prompt: false });
    setChecking(true);
    setError(undefined);
    try {
      setNotifyOn(!!token || (await notificationsAllowed()));
      const res = await authApi.check(id, token);
      if (res.status === 'pending') {
        setStage(res.stage);
        setAccountName(res.accountName);
      } else {
        if (res.status !== 'active') await pendingRegistration.clear();
        router.replace({ pathname: '/login', params: { ...loginIdParams(id), check: '1' } });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }, [id, router]);

  useEffect(() => {
    // Started from a microtask so no state is set synchronously during the effect.
    void Promise.resolve().then(check);
    const sub = AppState.addEventListener('change', (s) => s === 'active' && void check());
    return () => sub.remove();
  }, [check]);

  const enableNotifications = async () => {
    const token = await getPushToken({ prompt: true });
    if (token || (await notificationsAllowed())) {
      setNotifyOn(true);
      void check();
    } else {
      // Already denied once: the OS won't prompt again, so send them to Settings.
      await Linking.openSettings();
    }
  };

  const useDifferentAccount = async () => {
    await pendingRegistration.clear();
    router.replace('/login');
  };

  const steps: { title: string; detail: string; state: StepState }[] = [
    { title: 'Registration submitted', detail: 'We have received your details.', state: 'done' },
    {
      title: 'Approval by Ambuja Neotia',
      detail: stage === 'approved' ? 'Your registration has been approved.' : 'Our team is reviewing your registration.',
      state: stage === 'approved' ? 'done' : 'current',
    },
    {
      title: 'Account set up',
      detail: 'Your partner account and project access are being set up.',
      state: stage === 'approved' ? 'current' : 'upcoming',
    },
  ];

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={styles.container}>
        <BrandLogo />
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Ionicons name="hourglass-outline" size={28} color={colors.accentText} />
          </View>
          <Text style={styles.title}>Approval pending</Text>
          <Text style={styles.subtitle}>
            {accountName ? `${accountName} · ` : ''}{id ? describeLoginId(id) : ''}
          </Text>
        </View>

        <Card>
          {steps.map((st, i) => (
            <View key={st.title} style={styles.step}>
              <View style={styles.rail}>
                <View style={[styles.dot, st.state === 'done' && styles.dotDone, st.state === 'current' && styles.dotCurrent]}>
                  {st.state === 'done' ? <Ionicons name="checkmark" size={14} color={colors.white} /> : null}
                </View>
                {i < steps.length - 1 ? <View style={[styles.line, st.state === 'done' && styles.lineDone]} /> : null}
              </View>
              <View style={styles.stepBody}>
                <Text style={[styles.stepTitle, st.state === 'upcoming' && { color: colors.textMuted }]}>{st.title}</Text>
                <Text style={styles.stepDetail}>{st.state === 'upcoming' ? 'Next step' : st.detail}</Text>
              </View>
            </View>
          ))}
        </Card>

        <Text style={styles.note}>
          You can log in once your account is ready.{' '}
          {notifyOn === false
            ? 'Turn on notifications to be told as soon as it is.'
            : "We'll send you a notification as soon as it is."}
        </Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {notifyOn === false ? (
          <Button title="Turn on notifications" icon="notifications-outline" onPress={enableNotifications} style={{ marginTop: spacing.lg }} />
        ) : null}
        <Button
          title="Check status"
          icon="refresh"
          variant="secondary"
          loading={checking}
          onPress={check}
          style={{ marginTop: spacing.md }}
        />
        <Button
          title={id && !isMobileId(id) ? 'Use a different email' : 'Use a different mobile number'}
          variant="secondary"
          onPress={useDifferentAccount}
          style={{ marginTop: spacing.md }}
        />

        {env.useMock ? (
          <View style={styles.demo}>
            <Text style={styles.demoTitle}>Demo controls</Text>
            <Text style={styles.demoText}>Stand in for the admin portal and Salesforce.</Text>
            {stage === 'submitted' ? (
              <Button
                title="Admin approves"
                variant="secondary"
                onPress={() => {
                  if (id) mock.demoAdminApprove(id);
                  void check();
                }}
                style={{ marginTop: spacing.sm }}
              />
            ) : null}
            {stage === 'approved' ? (
              <Button
                title="Added in Salesforce + notify"
                variant="secondary"
                onPress={async () => {
                  if (!id) return;
                  mock.demoAddedInSalesforce(id);
                  await showDemoPartnerAddedNotification(id);
                }}
                style={{ marginTop: spacing.sm }}
              />
            ) : null}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { padding: spacing.xl, paddingBottom: spacing.xl * 2 },
  hero: { alignItems: 'center', marginTop: spacing.xl, marginBottom: spacing.lg },
  heroIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: 22, fontWeight: '800', color: colors.text, marginTop: spacing.md },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 4 },
  step: { flexDirection: 'row', gap: spacing.md },
  rail: { alignItems: 'center', width: 22 },
  dot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.border, backgroundColor: colors.card, alignItems: 'center', justifyContent: 'center' },
  dotDone: { backgroundColor: colors.success, borderColor: colors.success },
  dotCurrent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  line: { flex: 1, width: 2, backgroundColor: colors.border, marginVertical: 2, minHeight: 18 },
  lineDone: { backgroundColor: colors.success },
  stepBody: { flex: 1, paddingBottom: spacing.lg },
  stepTitle: { fontSize: 15, fontWeight: '700', color: colors.text },
  stepDetail: { fontSize: 13, color: colors.textMuted, marginTop: 2, lineHeight: 18 },
  note: { fontSize: 13.5, color: colors.textMuted, textAlign: 'center', marginTop: spacing.lg, lineHeight: 19 },
  error: { color: colors.danger, fontSize: 13, textAlign: 'center', marginTop: spacing.sm },
  demo: { marginTop: spacing.xl, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.border },
  demoTitle: { fontSize: 13, fontWeight: '700', color: colors.text },
  demoText: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
});
