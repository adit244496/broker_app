import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ApiError } from '@/api/client';
import { enquiryApi, leadFormApi, projectApi } from '@/api/services';
import { Button, ChipSelect, ErrorState, FormField, Loading, s } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { spacing } from '@/theme';
import type { LeadField, LeadValues, Project } from '@/types/models';
import { toSfDate, validators as v } from '@/utils/validation';

type Errors = Record<string, string | undefined>;

/** Checks one value as the backend will; the backend has the final say. */
function checkField(f: LeadField, value = ''): string | undefined {
  if (!value.trim()) return f.required ? `${f.label} is required` : undefined;
  if (f.type === 'phone') return v.mobile(value);
  if (f.type === 'email') return v.email(value.trim());
  if (f.type === 'date') return v.date(value);
  if (f.type === 'number') return /^-?\d+(\.\d+)?$/.test(value.trim()) ? undefined : 'Enter a number';
  return undefined;
}

export default function CreateLeadScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // The fields come from the admin portal (Settings -> Lead form). No broker field: the backend
  // attaches the logged-in broker's Salesforce Account Id.
  const setup = useAsync(() => Promise.all([leadFormApi.get(), projectApi.list()]));
  const [values, setValues] = useState<LeadValues>({});
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);

  if (setup.loading) return <Loading />;
  if (setup.error || !setup.data) return <ErrorState message={setup.error ?? ''} onRetry={setup.reload} />;
  const [fields, projects] = setup.data;
  const projectKey = fields.find((f) => f.type === 'project')?.key;
  const selectedProject = projects.find((p) => p.id === (projectKey ? values[projectKey] : undefined));

  const set = (f: LeadField) => (value: string) => {
    setValues((prev) => ({
      ...prev,
      [f.key]: value,
      // A different project may offer different configurations.
      ...(f.type === 'project' ? { configuration: '' } : {}),
    }));
    if (errors[f.key]) setErrors((e) => ({ ...e, [f.key]: undefined }));
  };

  const submit = async () => {
    const errs: Errors = {};
    for (const f of fields) {
      const err = checkField(f, values[f.key]);
      if (err) errs[f.key] = err;
    }
    setErrors(errs);
    if (Object.values(errs).some(Boolean)) return;

    const payload: LeadValues = {};
    for (const f of fields) {
      const value = values[f.key]?.trim();
      if (value) payload[f.key] = f.type === 'date' ? (toSfDate(value) ?? value) : value;
    }
    setSubmitting(true);
    try {
      const lead = await enquiryApi.create(payload);
      const [title, message] =
        lead.approvalStatus === 'Pending'
          ? ['Lead submitted', `${lead.projectName ?? 'This project'}'s sales manager will review it. It goes to Ambuja Neotia once approved; you can follow it under Leads.`]
          : ['Lead created', `${lead.enquiryNumber ?? 'Your lead'} has been submitted to Ambuja Neotia.`];
      Alert.alert(title, message, [{ text: 'OK', onPress: () => router.back() }]);
    } catch (e) {
      // 409: Salesforce already has a lead for this customer and project.
      const title = e instanceof ApiError && e.status === 409 ? 'Lead already exists' : 'Could not create lead';
      Alert.alert(title, (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + spacing.xl }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[s.sectionTitle, { marginBottom: spacing.md }]}>Customer details</Text>
        {fields.map((f) => (
          <LeadInput
            key={f.key}
            field={f}
            value={values[f.key] ?? ''}
            error={errors[f.key]}
            onChange={set(f)}
            projects={projects}
            selectedProject={selectedProject}
          />
        ))}
        <Button title="Submit Lead" icon="send" loading={submitting} onPress={submit} style={{ marginTop: spacing.md }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function LeadInput({
  field: f,
  value,
  error,
  onChange,
  projects,
  selectedProject,
}: {
  field: LeadField;
  value: string;
  error?: string;
  onChange: (v: string) => void;
  projects: Project[];
  selectedProject?: Project;
}) {
  const common = { label: f.label, required: f.required, value, onChangeText: onChange, error, placeholder: f.placeholder ?? undefined };
  switch (f.type) {
    case 'project':
      return (
        <ChipSelect
          label={f.label}
          required={f.required}
          options={projects.map((p) => p.id)}
          getLabel={(id) => projects.find((p) => p.id === id)?.name ?? id}
          value={value || undefined}
          onChange={onChange}
          error={error}
        />
      );
    case 'picklist': {
      // Configuration follows the chosen project when the project lists its own.
      const options = f.key === 'configuration' && selectedProject?.configurations?.length ? selectedProject.configurations : f.options;
      return <ChipSelect label={f.label} required={f.required} options={options} value={value || undefined} onChange={onChange} error={error} />;
    }
    case 'phone':
      return <FormField {...common} keyboardType="number-pad" maxLength={10} placeholder={f.placeholder ?? '10-digit mobile'} />;
    case 'email':
      return <FormField {...common} keyboardType="email-address" autoCapitalize="none" autoCorrect={false} />;
    case 'date':
      return <FormField {...common} keyboardType="numbers-and-punctuation" maxLength={10} placeholder="DD/MM/YYYY" />;
    case 'number':
      return <FormField {...common} keyboardType="decimal-pad" />;
    case 'textarea':
      return <FormField {...common} multiline />;
    default:
      return <FormField {...common} />;
  }
}
