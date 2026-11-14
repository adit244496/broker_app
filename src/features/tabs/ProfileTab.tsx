import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useAuth } from '@/auth/AuthContext';
import { Card, InfoRow, Loading, SectionTitle } from '@/components/ui';
import { env } from '@/config/env';
import { colors, spacing, TAB_BAR_HEIGHT } from '@/theme';
import type { AccountSection, ProfileDetail } from '@/types/models';
import { initials } from '@/utils/format';

export function ProfileTab() {
  const router = useRouter();
  const { user: p, signOut } = useAuth();
  if (!p) return <Loading />;

  const logout = () =>
    Alert.alert('Log out', 'Are you sure you want to log out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log out', style: 'destructive', onPress: () => void signOut() },
    ]);

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: TAB_BAR_HEIGHT + 48 }}>
      <View style={styles.hero}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials(p.name)}</Text>
        </View>
        <Text style={styles.name}>{p.name}</Text>
        <Text style={styles.role}>
          {p.role}
          {p.company ? ` · ${p.company}` : ''}
        </Text>
      </View>

      {/* Read-only: the details on the broker's Channel Partner account in Salesforce. */}
      {p.details ? null : (
        <>
          <SectionTitle>Contact</SectionTitle>
          <Card>
            <InfoRow label="Email" value={p.email} />
            <InfoRow label="Mobile" value={p.phone} />
            {p.landline ? <InfoRow label="Phone" value={p.landline} /> : null}
          </Card>
        </>
      )}

      {p.role === 'Channel Partner' && p.details ? (
        <>
          <AccountDetailCards details={p.details} />
          <Text style={styles.note}>To change any of these details, contact your Ambuja Neotia relationship manager.</Text>
        </>
      ) : p.role === 'Channel Partner' ? (
        <>
          <SectionTitle>Business</SectionTitle>
          <Card>
            <InfoRow label="Firm / Account" value={p.company} />
            {p.profession ? <InfoRow label="Profession" value={p.profession} /> : null}
            <InfoRow label="RERA No" value={p.reraNo} />
            <InfoRow label="PAN" value={p.pan} />
            <InfoRow label="GSTIN" value={p.gstin} />
            {p.website ? <InfoRow label="Website" value={p.website} /> : null}
          </Card>

          <SectionTitle>Address</SectionTitle>
          <Card>
            <InfoRow label="CP Address" value={p.cpAddress} />
          </Card>
          <Text style={styles.note}>To change any of these details, contact your Ambuja Neotia relationship manager.</Text>
        </>
      ) : null}

      <Card style={{ marginTop: spacing.lg, paddingVertical: spacing.sm }}>
        <MenuItem
          icon="key-outline"
          label={p.hasPassword ? 'Change password' : 'Set a password'}
          onPress={() => router.push('/password')}
        />
        <MenuItem icon="notifications-outline" label="Notifications" />
        <MenuItem icon="shield-checkmark-outline" label="Privacy & Security" />
        <MenuItem icon="help-circle-outline" label="Help & Support" />
        <MenuItem icon="log-out-outline" label="Log out" danger onPress={logout} last />
      </Card>

      <Text style={styles.version}>
        Version {Constants.expoConfig?.version}
        {env.useMock ? ' · Demo data' : ''}
      </Text>
    </ScrollView>
  );
}

const SECTION_TITLES: Record<AccountSection, string> = {
  business: 'Business',
  contact: 'Contact',
};

/**
 * The account's details as the backend lists them (the admin's account form: labels, order, sections).
 */
function AccountDetailCards({ details }: { details: ProfileDetail[] }) {
  const order: AccountSection[] = ['contact', 'business'];
  return (
    <>
      {order.map((section) => {
        const rows = details.filter((d) => d.section === section);
        if (!rows.length) return null;
        return (
          <View key={section}>
            <SectionTitle>{SECTION_TITLES[section]}</SectionTitle>
            <Card>
              {rows.map((r) => (
                <InfoRow key={r.key} label={r.label} value={r.value} />
              ))}
            </Card>
          </View>
        );
      })}
    </>
  );
}

function MenuItem({
  icon,
  label,
  onPress,
  danger,
  last,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress?: () => void;
  danger?: boolean;
  last?: boolean;
}) {
  const color = danger ? colors.danger : colors.text;
  return (
    <Pressable onPress={onPress} style={[styles.menu, !last && styles.menuBorder]}>
      <Ionicons name={icon} size={20} color={color} />
      <Text style={[styles.menuLabel, { color }]}>{label}</Text>
      {!danger ? <Ionicons name="chevron-forward" size={18} color={colors.textMuted} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  hero: { alignItems: 'center', paddingVertical: spacing.xl },
  avatar: { width: 84, height: 84, borderRadius: 42, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.white, fontSize: 30, fontWeight: '800' },
  name: { fontSize: 22, fontWeight: '800', color: colors.text, marginTop: spacing.md },
  role: { fontSize: 14, color: colors.textMuted, marginTop: 2 },
  menu: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: 14 },
  menuBorder: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  menuLabel: { flex: 1, fontSize: 15, fontWeight: '500' },
  note: { color: colors.textMuted, fontSize: 12, marginTop: spacing.sm },
  version: { textAlign: 'center', color: colors.textMuted, fontSize: 12, marginTop: spacing.xl },
});
