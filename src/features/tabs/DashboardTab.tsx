import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { dashboardApi } from '@/api/services';
import { useAuth } from '@/auth/AuthContext';
import { BrandLogo, Button, Card, ErrorState, Loading, OpportunityBadge, SectionTitle, StageBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { useRefreshWhenShown } from '@/hooks/useRefreshWhenShown';
import { colors, spacing, TAB_BAR_HEIGHT } from '@/theme';
import { CLOSED_STATUSES, isConverted } from '@/types/models';
import { shownStatus, statusColor } from '@/utils/brokerStage';
import { formatDate } from '@/utils/format';
import { useLeadsLink } from './LeadsLink';

export function DashboardTab() {
  const router = useRouter();
  const summary = useAsync(() => dashboardApi.getSummary());
  const { user } = useAuth();
  const { openLeads } = useLeadsLink();

  useRefreshWhenShown(summary.silentReload, 'dashboard');

  if (summary.loading && !summary.data) return <Loading />;
  if (summary.error && !summary.data) return <ErrorState message={summary.error} onRetry={summary.reload} />;
  const d = summary.data!;
  // The server leaves out the statuses an admin has hidden from brokers.
  const pipeline = d.pipeline.map((p) => ({ stage: p.status, count: p.count }));
  const opportunityPipeline = d.opportunityPipeline;

  // Qualified (Salesforce's converted status) and closed leads aren't open.
  const closedOnly = d.pipeline.filter((p) => CLOSED_STATUSES.includes(p.status)).reduce((n, p) => n + p.count, 0);
  const closed = closedOnly + d.bookings;

  const stats = [
    { label: 'Leads', value: d.totalEnquiries, icon: 'chatbubbles' as const, tint: colors.primarySoft, fg: colors.primary },
    { label: 'Open', value: d.totalEnquiries - closed, icon: 'time' as const, tint: '#E6F0F8', fg: '#2F6C9C' },
    { label: 'Visits Confirmed', value: d.visitsConfirmed, icon: 'calendar' as const, tint: colors.accentSoft, fg: colors.accentText },
    { label: 'Visits Done', value: d.visitsDone, icon: 'location' as const, tint: '#CFFAFE', fg: '#0E7490' },
    { label: 'Qualified', value: d.bookings, icon: 'checkmark-done' as const, tint: '#DCFCE7', fg: '#15803D' },
    { label: 'Booked', value: d.booked, icon: 'trophy' as const, tint: '#FEF0DD', fg: '#A35500' },
    { label: 'Closed', value: closedOnly, icon: 'close-circle' as const, tint: '#FEE2E2', fg: '#B91C1C' },
  ];

  return (
    <ScrollView
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: TAB_BAR_HEIGHT + 48 }}
      refreshControl={<RefreshControl refreshing={summary.refreshing} onRefresh={summary.refresh} />}
    >
      <BrandLogo style={{ marginBottom: spacing.lg }} />
      <Text style={styles.hello}>Hello{user ? `, ${user.name}` : ''} 👋</Text>
      <Text style={styles.sub}>Here’s how your leads are progressing</Text>

      <View style={styles.grid}>
        {stats.map((st) => (
          <Card key={st.label} style={styles.stat}>
            <View style={[styles.statIcon, { backgroundColor: st.tint }]}>
              <Ionicons name={st.icon} size={18} color={st.fg} />
            </View>
            <Text style={styles.statValue}>{st.value}</Text>
            <Text style={styles.statLabel}>{st.label}</Text>
          </Card>
        ))}
      </View>

      <View style={styles.actions}>
        <Button title="Create New Lead" icon="add-circle" style={{ flex: 1 }} onPress={() => router.push('/enquiries/new')} />
      </View>

      <SectionTitle>Lead pipeline</SectionTitle>
      <Pipeline rows={pipeline} onPress={(stage) => openLeads('leads', stage)} />

      <SectionTitle>Opportunity pipeline</SectionTitle>
      {opportunityPipeline.length ? (
        <Pipeline rows={opportunityPipeline} onPress={(stage) => openLeads('opportunities', stage)} />
      ) : (
        <Card>
          <Text style={styles.pipeEmpty}>
            {d.opportunities
              ? 'Your converted leads have no Opportunity stage yet.'
              : 'Leads appear here once Ambuja Neotia converts them into opportunities.'}
          </Text>
        </Card>
      )}

      <SectionTitle>Recent leads</SectionTitle>
      <View style={{ gap: spacing.md }}>
        {d.recentEnquiries.map((e) => (
          <Card key={e.id} onPress={() => router.push({ pathname: '/enquiries/[id]', params: { id: e.id } })}>
            <View style={styles.recentRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.recentName}>
                  {e.firstName} {e.lastName}
                </Text>
                <Text style={styles.recentMeta}>
                  {e.projectName} · {formatDate(e.createdDate)}
                </Text>
                {isConverted(e) ? (
                  <View style={{ marginTop: 6 }}>
                    <OpportunityBadge />
                  </View>
                ) : null}
              </View>
              {shownStatus(e) ? <StageBadge stage={shownStatus(e)!} /> : null}
            </View>
          </Card>
        ))}
      </View>
    </ScrollView>
  );
}

/** One bar per status or stage; tapping a row opens that list in the Leads tab. */
function Pipeline({ rows, onPress }: { rows: { stage: string; count: number }[]; onPress: (stage: string) => void }) {
  const max = Math.max(1, ...rows.map((p) => p.count));
  return (
    <Card>
      {rows.map((p) => (
        <Pressable
          key={p.stage}
          style={({ pressed }) => [styles.pipeRow, pressed && { opacity: 0.6 }]}
          onPress={() => onPress(p.stage)}
          disabled={!p.count}
          accessibilityRole="button"
          accessibilityLabel={`${p.stage}: ${p.count}`}
        >
          <Text style={styles.pipeLabel}>{p.stage}</Text>
          <View style={styles.pipeTrack}>
            <View style={[styles.pipeFill, { width: `${(p.count / max) * 100}%`, backgroundColor: statusColor(p.stage).fg }]} />
          </View>
          <Text style={styles.pipeCount}>{p.count}</Text>
        </Pressable>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  hello: { fontSize: 26, fontWeight: '800', color: colors.text },
  sub: { fontSize: 14, color: colors.textMuted, marginTop: 2, marginBottom: spacing.lg },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  stat: { width: '47.5%', padding: spacing.md },
  statIcon: { width: 34, height: 34, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  statValue: { fontSize: 26, fontWeight: '800', color: colors.text, marginTop: spacing.sm },
  statLabel: { fontSize: 13, color: colors.textMuted },
  actions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.lg },
  pipeRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6 },
  pipeLabel: { width: 130, fontSize: 12.5, color: colors.text },
  pipeTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: colors.bg, overflow: 'hidden' },
  pipeFill: { height: 8, borderRadius: 4 },
  pipeEmpty: { fontSize: 13.5, color: colors.textMuted },
  pipeCount: { width: 28, textAlign: 'right', fontSize: 13, fontWeight: '700', color: colors.text },
  recentRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  recentName: { fontSize: 15, fontWeight: '700', color: colors.text },
  recentMeta: { fontSize: 12.5, color: colors.textMuted, marginTop: 2 },
});
