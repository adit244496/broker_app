import { Ionicons } from '@expo/vector-icons';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { colors, radius, shadow, spacing, statusColors } from '@/theme';
import type { EnquiryStatus } from '@/types/models';

/** The site's logo is white on transparent, so it always sits on a brand-coloured band. */
export function BrandLogo({ style }: { style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[s.brand, style]}>
      <Image source={require('../../assets/logo.png')} style={s.brandLogo} resizeMode="contain" accessibilityLabel="Ambuja Neotia" />
    </View>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <View style={s.header}>
      <View style={{ flex: 1 }}>
        <Text style={s.headerTitle}>{title}</Text>
        {subtitle ? <Text style={s.headerSubtitle}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

export function Card({ children, style, onPress }: { children: ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void }) {
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [s.card, style, pressed && { opacity: 0.85 }]}>
        {children}
      </Pressable>
    );
  }
  return <View style={[s.card, style]}>{children}</View>;
}

export function Button({
  title,
  onPress,
  icon,
  variant = 'primary',
  loading,
  disabled,
  style,
}: {
  title: string;
  onPress: () => void;
  icon?: keyof typeof Ionicons.glyphMap;
  variant?: 'primary' | 'secondary';
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const primary = variant === 'primary';
  const fg = primary ? colors.white : colors.primary;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        s.button,
        primary ? s.buttonPrimary : s.buttonSecondary,
        (pressed || disabled) && { opacity: 0.7 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={fg} /> : null}
          <Text style={[s.buttonText, { color: fg }]}>{title}</Text>
        </>
      )}
    </Pressable>
  );
}

export function StatusBadge({ status }: { status: EnquiryStatus }) {
  const c = statusColors[status] ?? { fg: colors.textMuted, bg: colors.border };
  return (
    <View style={[s.badge, { backgroundColor: c.bg }]}>
      <Text style={[s.badgeText, { color: c.fg }]}>{status}</Text>
    </View>
  );
}

/** Marks a lead Salesforce has converted into an Opportunity. */
export function OpportunityBadge({ stage }: { stage?: string }) {
  return (
    <View style={[s.badge, s.oppBadge]}>
      <Ionicons name="trophy" size={12} color={colors.white} />
      <Text style={[s.badgeText, { color: colors.white }]} numberOfLines={1}>
        Opportunity{stage ? ` · ${stage}` : ''}
      </Text>
    </View>
  );
}

export function Pill({ text, color = colors.textMuted, bg = colors.bg }: { text: string; color?: string; bg?: string }) {
  return (
    <View style={[s.badge, { backgroundColor: bg }]}>
      <Text style={[s.badgeText, { color }]}>{text}</Text>
    </View>
  );
}

export function SearchBar({ value, onChangeText, placeholder }: { value: string; onChangeText: (t: string) => void; placeholder: string }) {
  return (
    <View style={s.search}>
      <Ionicons name="search" size={18} color={colors.textMuted} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        style={s.searchInput}
        returnKeyType="search"
        autoCorrect={false}
      />
      {value ? (
        <Pressable onPress={() => onChangeText('')} hitSlop={10}>
          <Ionicons name="close-circle" size={18} color={colors.textMuted} />
        </Pressable>
      ) : null}
    </View>
  );
}

export function Loading() {
  return (
    <View style={s.center}>
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

export function EmptyState({
  icon = 'file-tray-outline',
  title,
  message,
  action,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <View style={s.center}>
      <Ionicons name={icon} size={44} color={colors.textMuted} />
      <Text style={s.emptyTitle}>{title}</Text>
      {message ? <Text style={s.emptyMessage}>{message}</Text> : null}
      {action ? <View style={{ marginTop: spacing.lg }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <EmptyState
      icon="cloud-offline-outline"
      title="Something went wrong"
      message={message}
      action={<Button title="Retry" icon="refresh" variant="secondary" onPress={onRetry} />}
    />
  );
}

export function SectionTitle({ children, right }: { children: string; right?: ReactNode }) {
  return (
    <View style={s.sectionRow}>
      <Text style={s.sectionTitle}>{children}</Text>
      {right}
    </View>
  );
}

export function FormField({
  label,
  required,
  error,
  ...input
}: TextInputProps & { label: string; required?: boolean; error?: string }) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={s.label}>
        {label}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      <TextInput
        placeholderTextColor={colors.textMuted}
        {...input}
        style={[s.input, input.multiline && { height: 88, textAlignVertical: 'top' }, error && { borderColor: colors.danger }]}
      />
      {error ? <Text style={s.error}>{error}</Text> : null}
    </View>
  );
}

/** Single-select chip group, used for Salesforce picklists. */
export function ChipSelect<T extends string>({
  label,
  options,
  value,
  onChange,
  required,
  error,
  getLabel = (o) => o,
}: {
  label: string;
  options: readonly T[];
  value?: T;
  onChange: (v: T) => void;
  required?: boolean;
  error?: string;
  getLabel?: (o: T) => string;
}) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={s.label}>
        {label}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      <View style={s.chips}>
        {options.map((o) => {
          const active = o === value;
          return (
            <Pressable key={o} onPress={() => onChange(o)} style={[s.chip, active && s.chipActive]}>
              <Text style={[s.chipText, active && { color: colors.white }]}>{getLabel(o)}</Text>
            </Pressable>
          );
        })}
      </View>
      {error ? <Text style={s.error}>{error}</Text> : null}
    </View>
  );
}

export function InfoRow({ label, value }: { label: string; value?: string }) {
  return (
    <View style={s.infoRow}>
      <Text style={s.infoLabel}>{label}</Text>
      <Text style={s.infoValue}>{value || '—'}</Text>
    </View>
  );
}

export const s = StyleSheet.create({
  brand: { alignItems: 'center', paddingVertical: spacing.lg, paddingHorizontal: spacing.xl, backgroundColor: colors.primary, borderRadius: radius.md, borderBottomWidth: 3, borderBottomColor: colors.accent },
  brandLogo: { width: 181, height: 24 },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.md },
  headerTitle: { fontSize: 26, fontWeight: '800', color: colors.text },
  headerSubtitle: { fontSize: 13, color: colors.textMuted, marginTop: 2 },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.lg, ...shadow },
  button: { height: 46, borderRadius: radius.md, paddingHorizontal: spacing.lg, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  buttonPrimary: { backgroundColor: colors.primary },
  buttonSecondary: { backgroundColor: colors.primarySoft },
  buttonText: { fontSize: 15, fontWeight: '700' },
  badge: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  badgeText: { fontSize: 11.5, fontWeight: '700' },
  oppBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: colors.success, maxWidth: '100%' },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.md,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl, minHeight: 300 },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: colors.text, marginTop: spacing.md },
  emptyMessage: { fontSize: 14, color: colors.textMuted, marginTop: 4, textAlign: 'center' },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.xl, marginBottom: spacing.md },
  sectionTitle: { fontSize: 17, fontWeight: '700', color: colors.text },
  label: { fontSize: 13, fontWeight: '600', color: colors.text, marginBottom: 6 },
  input: {
    height: 46,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 15,
    color: colors.text,
    backgroundColor: colors.card,
  },
  error: { color: colors.danger, fontSize: 12, marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text },
  infoRow: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  infoLabel: { fontSize: 12, color: colors.textMuted },
  infoValue: { fontSize: 15, color: colors.text, marginTop: 2 },
});
