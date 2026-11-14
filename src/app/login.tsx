import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { authApi } from '@/api/services';
import { useAuth } from '@/auth/AuthContext';
import {
  describeLoginId,
  isMobileId,
  loginIdFromParams,
  loginIdParams,
  normalizeEmail,
  normalizeMobile,
  type LoginId,
} from '@/auth/loginId';
import { pendingRegistration } from '@/auth/pendingRegistration';
import { BrandLogo, Button, Card } from '@/components/ui';
import { env } from '@/config/env';
import { colors, radius, spacing } from '@/theme';
import type { OtpRequestResult, PartnerLookup, Session } from '@/types/models';
import { validators } from '@/utils/validation';

const RESEND_SECONDS = 30;

type Mode = 'mobile' | 'email';
type Step = 'id' | 'password' | 'code';

export default function LoginScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  // `check=1` (from the pending screen or the "account ready" notification) looks the mobile/email up on arrival.
  const params = useLocalSearchParams<{ mobile?: string; email?: string; check?: string }>();
  // Mobile is the default; email stays available for brokers who prefer it.
  const [mode, setMode] = useState<Mode>(params.email && !params.mobile ? 'email' : 'mobile');
  const [mobile, setMobile] = useState(params.mobile ? normalizeMobile(params.mobile) : '');
  const [email, setEmail] = useState(params.email ?? '');
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [step, setStep] = useState<Step>('id');
  const [lookup, setLookup] = useState<PartnerLookup>();
  const [sent, setSent] = useState<OtpRequestResult>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const otpRef = useRef<ComponentRef<typeof TextInput>>(null);
  const passwordRef = useRef<ComponentRef<typeof TextInput>>(null);

  const id: LoginId = mode === 'mobile' ? { mobile: normalizeMobile(mobile) } : { email: normalizeEmail(email) };
  const what = mode === 'mobile' ? 'mobile number' : 'email';

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  /**
   * Looks the mobile/email up in Salesforce first. Returns true when the partner may log in; otherwise
   * shows why (register, rejected, inactive) or opens the pending screen.
   */
  const checkAccount = async (value: LoginId): Promise<boolean> => {
    const err = isMobileId(value) ? validators.mobile(value.mobile) : validators.email(value.email);
    setError(err);
    setLookup(undefined);
    if (err) return false;
    const res = await authApi.check(value);
    if (res.status === 'pending') {
      await pendingRegistration.set(value);
      router.push({ pathname: '/pending', params: loginIdParams(value) });
      return false;
    }
    if (res.status !== 'active') await pendingRegistration.clear();
    setLookup(res);
    return res.status === 'active';
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(undefined);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sendCode = () =>
    run(async () => {
      if (!(await checkAccount(id))) return;
      setSent(await authApi.requestOtp(id));
      setStep('code');
      setOtp('');
      setResendIn(RESEND_SECONDS);
      setTimeout(() => otpRef.current?.focus(), 300);
    });

  const choosePassword = () =>
    run(async () => {
      if (!(await checkAccount(id))) return;
      setStep('password');
      setTimeout(() => passwordRef.current?.focus(), 300);
    });

  const finish = async (session: Session) => {
    await pendingRegistration.clear();
    await signIn(session);
    // The auth guard in _layout swaps to the app automatically.
  };

  const verifyCode = () => {
    if (!/^\d{6}$/.test(otp)) return setError('Enter the 6-digit code');
    return run(async () => finish(await authApi.verifyOtp(id, otp)));
  };

  const loginWithPassword = () => {
    if (!password) return setError('Enter your password');
    return run(async () => finish(await authApi.passwordLogin(id, password)));
  };

  const resend = () =>
    run(async () => {
      setSent(await authApi.requestOtp(id));
      setResendIn(RESEND_SECONDS);
    });

  // Arriving with a mobile/email to check, or reopening the app with a registration still pending.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const fromParams = params.check === '1' ? loginIdFromParams(params) : undefined;
      const value = fromParams ?? (await pendingRegistration.get());
      if (!value || cancelled) return;
      if (isMobileId(value)) {
        setMode('mobile');
        setMobile(value.mobile);
      } else {
        setMode('email');
        setEmail(value.email);
      }
      void run(async () => {
        await checkAccount(value);
      });
    })();
    return () => {
      cancelled = true;
    };
    // Runs once per arrival; checkAccount is recreated every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.check, params.mobile, params.email]);

  const back = () => {
    setStep('id');
    setError(undefined);
    setPassword('');
    setOtp('');
  };

  const clearFeedback = () => {
    setError(undefined);
    setLookup(undefined);
  };

  const switchMode = () => {
    setMode((m) => (m === 'mobile' ? 'email' : 'mobile'));
    clearFeedback();
  };

  const goRegister = () => router.push({ pathname: '/register', params: loginIdParams(id) });

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={[styles.blob, styles.blobA]} />
      <View style={[styles.blob, styles.blobB]} />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <BrandLogo />
          <Text style={styles.tagline}>Channel Partner Portal</Text>

          <Card style={styles.card}>
            {step === 'id' ? (
              <>
                <Text style={styles.title}>Log in</Text>
                <Text style={styles.subtitle}>Enter the {what} registered with your Channel Partner account.</Text>
                {mode === 'mobile' ? (
                  <View style={[styles.input, styles.phoneRow, error && { borderColor: colors.danger }]}>
                    <Text style={styles.phonePrefix}>+91</Text>
                    <TextInput
                      value={mobile}
                      onChangeText={(t) => {
                        // Pasted or autofilled numbers may carry +91, spaces or a leading 0.
                        const digits = t.replace(/\D/g, '');
                        setMobile(digits.length > 10 ? digits.slice(-10) : digits);
                        clearFeedback();
                      }}
                      placeholder="10-digit mobile number"
                      placeholderTextColor={colors.textMuted}
                      keyboardType="phone-pad"
                      autoComplete="tel"
                      textContentType="telephoneNumber"
                      maxLength={16}
                      returnKeyType="send"
                      onSubmitEditing={sendCode}
                      style={styles.phoneInput}
                    />
                  </View>
                ) : (
                  <TextInput
                    value={email}
                    onChangeText={(t) => {
                      setEmail(t);
                      clearFeedback();
                    }}
                    placeholder="name@company.com"
                    placeholderTextColor={colors.textMuted}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    autoCorrect={false}
                    autoComplete="email"
                    textContentType="emailAddress"
                    returnKeyType="send"
                    onSubmitEditing={sendCode}
                    style={[styles.input, error && { borderColor: colors.danger }]}
                  />
                )}
                {error ? <Text style={styles.error}>{error}</Text> : null}
                <LookupNotice result={lookup} what={what} onRegister={goRegister} />
                <Button
                  title={mode === 'mobile' ? 'Send OTP by SMS' : 'Email me a login code'}
                  icon={mode === 'mobile' ? 'chatbubble-ellipses-outline' : 'mail-outline'}
                  loading={busy}
                  onPress={sendCode}
                  style={{ marginTop: spacing.lg }}
                />
                <Button
                  title="Log in with password"
                  icon="key-outline"
                  variant="secondary"
                  disabled={busy}
                  onPress={choosePassword}
                  style={{ marginTop: spacing.md }}
                />
                <Pressable onPress={switchMode} disabled={busy} hitSlop={8} style={styles.switch}>
                  <Text style={styles.link}>{mode === 'mobile' ? 'Use email instead' : 'Use mobile number instead'}</Text>
                </Pressable>
              </>
            ) : step === 'password' ? (
              <>
                <Text style={styles.title}>Enter your password</Text>
                <Text style={styles.subtitle}>{describeLoginId(id)}</Text>
                <TextInput
                  ref={passwordRef}
                  value={password}
                  onChangeText={(t) => {
                    setPassword(t);
                    setError(undefined);
                  }}
                  placeholder="Password"
                  placeholderTextColor={colors.textMuted}
                  secureTextEntry
                  autoCapitalize="none"
                  autoComplete="current-password"
                  textContentType="password"
                  returnKeyType="go"
                  onSubmitEditing={loginWithPassword}
                  style={[styles.input, error && { borderColor: colors.danger }]}
                />
                {error ? <Text style={styles.error}>{error}</Text> : null}
                <Button title="Log in" icon="log-in-outline" loading={busy} onPress={loginWithPassword} style={{ marginTop: spacing.lg }} />
                <View style={styles.links}>
                  <Pressable onPress={back} hitSlop={8}>
                    <Text style={styles.link}>Change {what}</Text>
                  </Pressable>
                  <Pressable onPress={sendCode} disabled={busy} hitSlop={8}>
                    <Text style={styles.link}>Forgot password? Send me a code</Text>
                  </Pressable>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.title}>{sent?.channel === 'email' ? 'Check your email' : 'Enter the OTP'}</Text>
                <Text style={styles.subtitle}>
                  {sent?.channel === 'email'
                    ? `Enter the 6-digit code we sent to ${sent.masked}. It may take a minute; check your spam folder too.`
                    : `Enter the 6-digit code we sent by SMS to ${sent?.masked ?? describeLoginId(id)}.`}
                </Text>
                <TextInput
                  ref={otpRef}
                  value={otp}
                  onChangeText={(t) => {
                    setOtp(t.replace(/\D/g, ''));
                    setError(undefined);
                  }}
                  placeholder="••••••"
                  placeholderTextColor={colors.textMuted}
                  keyboardType="number-pad"
                  maxLength={6}
                  style={[styles.otpInput, error && { borderColor: colors.danger }]}
                  // Android offers the code from the incoming SMS; iOS from Messages or Mail.
                  autoComplete={Platform.OS === 'android' ? 'sms-otp' : 'one-time-code'}
                  textContentType="oneTimeCode"
                  onSubmitEditing={verifyCode}
                />
                {error ? <Text style={styles.error}>{error}</Text> : null}
                <Button title="Verify & Log in" icon="log-in-outline" loading={busy} onPress={verifyCode} style={{ marginTop: spacing.lg }} />
                <View style={styles.links}>
                  <Pressable onPress={back} hitSlop={8}>
                    <Text style={styles.link}>Change {what}</Text>
                  </Pressable>
                  <Pressable disabled={resendIn > 0 || busy} onPress={resend} hitSlop={8}>
                    <Text style={[styles.link, resendIn > 0 && { color: colors.textMuted }]}>
                      {resendIn > 0 ? `Resend in ${resendIn}s` : 'Resend code'}
                    </Text>
                  </Pressable>
                </View>
              </>
            )}
          </Card>

          {step === 'id' ? (
            <View style={styles.registerRow}>
              <Text style={styles.registerText}>New channel partner?</Text>
              <Pressable onPress={goRegister} hitSlop={8}>
                <Text style={styles.link}>Register here</Text>
              </Pressable>
            </View>
          ) : null}

          {env.useMock ? (
            <Text style={styles.demo}>
              Demo mode · 9830012345 or contact@abcbroker.in (code 123456) · 9007711223 pending · 9836677889 approved,
              not yet added · 9123450987 rejected
            </Text>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function LookupNotice({ result, what, onRegister }: { result?: PartnerLookup; what: string; onRegister: () => void }) {
  // An active partner goes straight on to the code or password step.
  if (!result || result.status === 'pending' || result.status === 'active') return null;
  const content = {
    not_found: {
      icon: 'person-add-outline' as const,
      color: colors.primary,
      bg: colors.primarySoft,
      title: 'No account found',
      message: `This ${what} is not registered as a Channel Partner. Register first to get access.`,
    },
    rejected: {
      icon: 'close-circle-outline' as const,
      color: colors.danger,
      bg: '#FEE2E2',
      title: 'Registration not approved',
      message: `${result.status === 'rejected' && result.reason ? `${result.reason} ` : ''}Please contact your Ambuja Neotia relationship manager.`,
    },
    inactive: {
      icon: 'alert-circle-outline' as const,
      color: colors.danger,
      bg: '#FEE2E2',
      title: 'Account inactive',
      message: 'Your account is inactive. Please contact your Ambuja Neotia relationship manager.',
    },
  }[result.status];

  return (
    <View style={[styles.notice, { backgroundColor: content.bg }]}>
      <Ionicons name={content.icon} size={20} color={content.color} />
      <View style={{ flex: 1 }}>
        <Text style={[styles.noticeTitle, { color: content.color }]}>{content.title}</Text>
        <Text style={styles.noticeText}>{content.message}</Text>
        {result.status === 'not_found' ? (
          <Button title="Register as Channel Partner" icon="person-add" onPress={onRegister} style={{ marginTop: spacing.md, height: 40 }} />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl },
  blob: { position: 'absolute', width: 340, height: 340, borderRadius: 170, opacity: 0.16 },
  blobA: { backgroundColor: colors.primary, top: -140, right: -120 },
  blobB: { backgroundColor: colors.accent, bottom: -120, left: -140 },
  tagline: { textAlign: 'center', fontSize: 14, color: colors.textMuted, marginTop: spacing.md, marginBottom: spacing.xl },
  card: { padding: spacing.xl },
  title: { fontSize: 20, fontWeight: '800', color: colors.text },
  subtitle: { fontSize: 13.5, color: colors.textMuted, marginTop: 4, marginBottom: spacing.lg, lineHeight: 19 },
  input: {
    height: 50,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    fontSize: 16,
    color: colors.text,
  },
  phoneRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 0 },
  phonePrefix: { paddingLeft: spacing.md, paddingRight: spacing.sm, fontSize: 16, fontWeight: '600', color: colors.text },
  phoneInput: { flex: 1, height: '100%', paddingRight: spacing.md, fontSize: 16, color: colors.text },
  otpInput: {
    height: 56,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    textAlign: 'center',
    fontSize: 24,
    letterSpacing: 10,
    fontWeight: '700',
    color: colors.text,
    backgroundColor: colors.card,
  },
  error: { color: colors.danger, fontSize: 12.5, marginTop: 6 },
  switch: { alignSelf: 'center', marginTop: spacing.lg },
  links: { flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.lg },
  link: { color: colors.primary, fontWeight: '700', fontSize: 14 },
  notice: { flexDirection: 'row', gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md },
  noticeTitle: { fontSize: 14, fontWeight: '700' },
  noticeText: { fontSize: 13, color: colors.text, marginTop: 2, lineHeight: 18 },
  registerRow: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: spacing.xl },
  registerText: { fontSize: 14, color: colors.textMuted },
  demo: { textAlign: 'center', fontSize: 12, color: colors.textMuted, marginTop: spacing.lg, lineHeight: 17 },
});
