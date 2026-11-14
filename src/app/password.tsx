import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, Text } from 'react-native';
import { authApi } from '@/api/services';
import { useAuth } from '@/auth/AuthContext';
import { Button, FormField } from '@/components/ui';
import { colors, spacing } from '@/theme';

const MIN_LENGTH = 8;

/** Set a password after a code login (SMS or email), or change it. Codes keep working either way. */
export default function PasswordScreen() {
  const router = useRouter();
  const { session, signIn } = useAuth();
  const hasPassword = !!session?.user.hasPassword;
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const errs: typeof errors = {};
    if (next.length < MIN_LENGTH) errs.next = `Use at least ${MIN_LENGTH} characters`;
    if (confirm !== next) errs.confirm = "Passwords don't match";
    setErrors(errs);
    if (Object.keys(errs).length || !session) return;
    setBusy(true);
    try {
      await authApi.setPassword(next, current || undefined);
      await signIn({ ...session, user: { ...session.user, hasPassword: true } });
      Alert.alert(
        hasPassword ? 'Password changed' : 'Password set',
        'You can now log in with your mobile number (or email) and password, or with a code. Other devices have been logged out.',
        [{ text: 'OK', onPress: () => router.back() }],
      );
    } catch (e) {
      const message = (e as Error).message;
      if (/current password/i.test(message)) setErrors({ current: message });
      else Alert.alert('Could not save password', message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: spacing.lg }} keyboardShouldPersistTaps="handled">
        <Text style={{ color: colors.textMuted, fontSize: 13.5, lineHeight: 19, marginBottom: spacing.lg }}>
          {hasPassword
            ? 'Change the password you use to log in. If you logged in with a code (SMS or email), you can leave the current password empty.'
            : 'Set a password so you can log in without waiting for a code. Codes will keep working.'}
        </Text>
        {hasPassword ? (
          <FormField
            label="Current password"
            secureTextEntry
            autoCapitalize="none"
            autoComplete="current-password"
            textContentType="password"
            value={current}
            onChangeText={setCurrent}
            error={errors.current}
          />
        ) : null}
        <FormField
          label="New password"
          required
          secureTextEntry
          autoCapitalize="none"
          autoComplete="new-password"
          textContentType="newPassword"
          placeholder={`At least ${MIN_LENGTH} characters`}
          value={next}
          onChangeText={setNext}
          error={errors.next}
        />
        <FormField
          label="Confirm new password"
          required
          secureTextEntry
          autoCapitalize="none"
          autoComplete="new-password"
          textContentType="newPassword"
          value={confirm}
          onChangeText={setConfirm}
          error={errors.confirm}
        />
        <Button
          title={hasPassword ? 'Change password' : 'Set password'}
          icon="key-outline"
          loading={busy}
          onPress={save}
          style={{ marginTop: spacing.md }}
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
