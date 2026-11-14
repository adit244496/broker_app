import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, Text, View, type KeyboardTypeOptions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { authApi } from '@/api/services';
import { loginIdParams, normalizeMobile } from '@/auth/loginId';
import { pendingRegistration } from '@/auth/pendingRegistration';
import { Button, ChipSelect, ErrorState, FormField, Loading, s } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { getPushToken } from '@/notifications/push';
import { colors, spacing } from '@/theme';
import type { AccountForm, AccountFormField, AccountSection, RegistrationValues } from '@/types/models';
import { validators as v } from '@/utils/validation';

const SECTIONS: AccountSection[] = ['business', 'contact'];

const KEYBOARD: Partial<Record<AccountFormField['type'], KeyboardTypeOptions>> = {
  mobile: 'number-pad',
  tel: 'phone-pad',
  email: 'email-address',
  number: 'decimal-pad',
  url: 'url',
  pincode: 'number-pad',
};
const MAX_LENGTH: Partial<Record<AccountFormField['type'], number>> = { mobile: 10, pan: 10, gstin: 15, pincode: 6 };
const FORMAT: Partial<Record<AccountFormField['type'], (value?: string) => string | undefined>> = {
  mobile: v.mobile,
  tel: v.tel,
  email: v.email,
  number: v.number,
  url: v.url,
  pan: v.pan,
  gstin: v.gstin,
  pincode: v.pin,
};

/**
 * Self-registration for brokers without a Channel Partner account. The fields come from the portal
 * (Settings -> Account form), so admins can add or remove them without an app update.
 */
export default function RegisterScreen() {
  const form = useAsync(() => authApi.getAccountForm());
  if (form.loading && !form.data) return <Loading />;
  if (!form.data) return <ErrorState message={form.error ?? "Couldn't load the form."} onRetry={form.reload} />;
  return <RegistrationForm form={form.data} />;
}

function RegistrationForm({ form }: { form: AccountForm }) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { mobile, email } = useLocalSearchParams<{ mobile?: string; email?: string }>();
  const fields = form.fields;
  const [values, setValues] = useState<RegistrationValues>(() => {
    const init: RegistrationValues = {};
    for (const f of fields) if (f.defaultValue) init[f.key] = f.defaultValue;
    if (mobile) init.mobile = mobile;
    if (email) init.email = email;
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [submitting, setSubmitting] = useState(false);

  const set = (key: string) => (value: string) => {
    setValues((x) => ({ ...x, [key]: value }));
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const submit = async () => {
    const out: RegistrationValues = {};
    const errs: Record<string, string> = {};
    for (const f of fields) {
      const value = values[f.key]?.trim() ?? '';
      if (!value) {
        if (f.required) errs[f.key] = 'This field is required';
        continue;
      }
      const formatted = f.type === 'pan' || f.type === 'gstin' ? value.toUpperCase() : value;
      const err = f.type === 'picklist' ? (f.options.includes(value) ? undefined : 'Choose one of the options') : FORMAT[f.type]?.(formatted);
      if (err) errs[f.key] = err;
      else out[f.key] = formatted;
    }
    setErrors(errs);
    if (Object.keys(errs).length) {
      Alert.alert('Check the form', 'Some fields need your attention.');
      return;
    }

    setSubmitting(true);
    try {
      // Asked here, in context: the push is how they'll hear their account is ready.
      const pushToken = await getPushToken({ prompt: true });
      await authApi.register(out, pushToken);
      // Mobile is how they'll log in once approved, so the status is tracked by it.
      const id = { mobile: normalizeMobile(out.mobile ?? '') };
      await pendingRegistration.set(id);
      router.replace({ pathname: '/pending', params: loginIdParams(id) });
    } catch (e) {
      Alert.alert('Registration failed', (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const renderField = (f: AccountFormField) => {
    if (f.type === 'picklist') {
      return (
        <ChipSelect
          key={f.key}
          label={f.label}
          required={f.required}
          options={f.options}
          value={values[f.key]}
          onChange={set(f.key)}
          error={errors[f.key]}
        />
      );
    }
    return (
      <FormField
        key={f.key}
        label={f.label}
        required={f.required}
        placeholder={f.placeholder ?? undefined}
        value={values[f.key] ?? ''}
        onChangeText={set(f.key)}
        error={errors[f.key]}
        multiline={f.type === 'textarea'}
        keyboardType={KEYBOARD[f.type]}
        maxLength={MAX_LENGTH[f.type]}
        autoCapitalize={f.type === 'pan' || f.type === 'gstin' ? 'characters' : f.type === 'email' || f.type === 'url' ? 'none' : 'sentences'}
      />
    );
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + spacing.xl }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={{ color: colors.textMuted, fontSize: 13.5, lineHeight: 19, marginBottom: spacing.lg }}>
          Don’t have a Channel Partner account with Ambuja Neotia yet? Fill in your details below. You’ll log in with
          your email or mobile number once you’re approved.
        </Text>

        {SECTIONS.map((section) => {
          const inSection = fields.filter((f) => f.section === section);
          if (!inSection.length) return null;
          return (
            <View key={section}>
              <Text style={[s.sectionTitle, { marginVertical: spacing.md }]}>{form.sections[section]}</Text>
              {inSection.map(renderField)}
            </View>
          );
        })}

        <Text style={{ color: colors.textMuted, fontSize: 12, marginVertical: spacing.lg }}>
          Ambuja Neotia reviews every registration. Your Channel Partner account is created once you’re approved.
        </Text>
        <Button title="Submit Registration" icon="checkmark-circle" loading={submitting} onPress={submit} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
