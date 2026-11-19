import { Ionicons } from '@expo/vector-icons';
import { Stack, useLocalSearchParams } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { enquiryApi } from '@/api/services';
import { Card, ErrorState, InfoRow, Loading, SectionTitle, StageBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { colors, spacing } from '@/theme';
import { awaitingApproval, CLOSED_STATUSES, isConverted, type EnquiryStatus } from '@/types/models';
import { historySteps, shownStatus, statusColor } from '@/utils/brokerStage';
import { formatDate } from '@/utils/format';
import { visitStage } from '@/utils/visits';

// The progress tracker: Salesforce's statuses grouped into the stages a broker cares about. Closed statuses
// (Unqualified, DND, No action needed) are shown separately.
const STAGES = ['New', 'Working', 'Visit confirmed', 'Visit done', 'Qualified'] as const;
const STAGE_OF: Partial<Record<EnquiryStatus, number>> = {
  New: 0,
  Working: 1,
  'Follow up': 1,
  Unanswered: 1,
  'Not Reachable': 1,
  Nurturing: 1,
  'Visit confirmed': 2,
  Qualified: 4,
};

export default function EnquiryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useAsync(() => Promise.all([enquiryApi.get(id), enquiryApi.statusHistory(id)]), [id]);

  if (data.loading && !data.data) return <Loading />;
  if (data.error || !data.data) return <ErrorState message={data.error ?? ''} onRetry={data.reload} />;
  const [e, history] = data.data;
  // "Visit done" once the site visit date has passed (Salesforce has no status for it).
  const converted = isConverted(e);
  // Converted into an Opportunity = qualified, whatever the Lead Status still says.
  const currentStage = converted
    ? STAGES.length - 1
    : visitStage(e) === 'done' && e.status === 'Visit confirmed'
      ? 3
      : (STAGE_OF[e.status] ?? 0);
  const closed = !converted && CLOSED_STATUSES.includes(e.status);
  // Not in Salesforce yet (waiting for the sales manager) or rejected: no progress to track.
  const approval = awaitingApproval(e) ? e.approvalStatus : undefined;
  // Only the steps an admin hasn't hidden from brokers (the server filters them).
  const steps = historySteps(history);
  const stage = shownStatus(e);

  return (
    <ScrollView
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xl * 2 }}
      refreshControl={<RefreshControl refreshing={data.refreshing} onRefresh={data.refresh} />}
    >
      <Stack.Screen options={{ title: e.enquiryNumber ?? 'Lead' }} />

      <Card>
        <View style={styles.headRow}>
          <Text style={styles.name}>
            {e.firstName} {e.lastName}
          </Text>
          {stage ? <StageBadge stage={stage} /> : null}
        </View>
        <Text style={styles.sub}>Last updated {formatDate(e.lastModifiedDate ?? e.createdDate, true)}</Text>

        {approval ? null : closed ? (
          <View style={styles.lost}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
            <Text style={{ color: colors.textMuted, fontWeight: '600' }}>This lead was closed.</Text>
          </View>
        ) : (
          <View style={styles.tracker}>
            {STAGES.map((stage, i) => {
              const done = i <= currentStage;
              return (
                <View key={stage} style={styles.trackStep}>
                  <View style={[styles.trackBar, { backgroundColor: done ? colors.primary : colors.border }]} />
                  <Text style={[styles.trackLabel, done && { color: colors.primary, fontWeight: '700' }]} numberOfLines={2}>
                    {stage}
                  </Text>
                </View>
              );
            })}
          </View>
        )}
      </Card>

      {approval === 'Pending' ? (
        <View style={[styles.oppBanner, { backgroundColor: colors.accentSoft }]}>
          <Ionicons name="hourglass-outline" size={22} color={colors.accentText} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.oppTitle, { color: colors.accentText }]}>Waiting for approval</Text>
            <Text style={[styles.oppText, { color: colors.accentText }]}>
              {"The project's sales manager reviews new leads. It goes to Ambuja Neotia once approved."}
            </Text>
          </View>
        </View>
      ) : approval === 'Rejected' ? (
        <View style={[styles.oppBanner, { backgroundColor: '#FEE2E2' }]}>
          <Ionicons name="close-circle" size={22} color={colors.danger} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.oppTitle, { color: colors.danger }]}>Not approved</Text>
            <Text style={[styles.oppText, { color: colors.text }]}>{e.rejectionReason ?? 'The sales manager did not approve this lead.'}</Text>
          </View>
        </View>
      ) : null}

      {converted ? (
        <View style={styles.oppBanner}>
          <Ionicons name="trophy" size={22} color={colors.white} />
          <View style={{ flex: 1 }}>
            <Text style={styles.oppTitle}>Converted to Opportunity</Text>
            <Text style={styles.oppText}>
              {e.opportunityStage ? `Stage: ${e.opportunityStage}` : 'Salesforce is now tracking this customer as an opportunity.'}
            </Text>
          </View>
        </View>
      ) : null}

      <SectionTitle>Progress</SectionTitle>
      <Card>
        {steps.map((h, i) => {
          const last = i === steps.length - 1;
          return (
            <View key={`${h.value}-${h.date}`} style={styles.tlRow}>
              <View style={styles.tlRail}>
                <View style={[styles.tlDot, { backgroundColor: statusColor(h.value).fg }]} />
                {!last ? <View style={styles.tlLine} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: last ? 0 : spacing.lg }}>
                <Text style={styles.tlStatus}>{h.value}</Text>
                {h.converted ? <Text style={styles.tlConverted}>Converted to Opportunity</Text> : null}
                <Text style={styles.tlMeta}>{formatDate(h.date, true)}</Text>
                {h.note ? <Text style={styles.tlNote}>{h.note}</Text> : null}
              </View>
            </View>
          );
        })}
      </Card>

      <SectionTitle>Details</SectionTitle>
      <Card>
        <InfoRow label="Mobile" value={`${e.countryCode ?? ''} ${e.mobile}`.trim()} />
        <InfoRow label="Email" value={e.email} />
        <InfoRow label="Project" value={e.projectName} />
        <InfoRow label="Configuration" value={e.configuration} />
        <InfoRow label="Budget" value={e.budget} />
        {e.opportunityStage ? <InfoRow label="Opportunity Stage" value={e.opportunityStage} /> : null}
        {e.siteVisitDate ? (
          <InfoRow label="Site Visit" value={formatDate(e.siteVisitDate, e.siteVisitDate.length > 10)} />
        ) : null}
        <InfoRow label="Preferred Site Visit" value={formatDate(e.preferredVisitDate)} />
        <InfoRow label="Channel Partner" value={e.brokerName} />
        <InfoRow label="Remarks" value={e.remarks} />
        <InfoRow label="Created" value={formatDate(e.createdDate, true)} />
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  headRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md },
  name: { flex: 1, fontSize: 20, fontWeight: '800', color: colors.text },
  sub: { fontSize: 12.5, color: colors.textMuted, marginTop: 4 },
  tracker: { flexDirection: 'row', gap: 4, marginTop: spacing.lg },
  trackStep: { flex: 1 },
  trackBar: { height: 5, borderRadius: 3 },
  trackLabel: { fontSize: 9.5, color: colors.textMuted, marginTop: 6 },
  oppBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginTop: spacing.md,
    padding: spacing.lg,
    borderRadius: 16,
    backgroundColor: colors.success,
  },
  oppTitle: { color: colors.white, fontSize: 16, fontWeight: '800' },
  oppText: { color: colors.white, fontSize: 13, marginTop: 2, opacity: 0.95 },
  tlConverted: { color: colors.success, fontWeight: '700', fontSize: 12.5, marginTop: 2 },
  lost: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: spacing.lg },
  tlRow: { flexDirection: 'row', gap: spacing.md },
  tlRail: { alignItems: 'center', width: 14 },
  tlDot: { width: 12, height: 12, borderRadius: 6, marginTop: 3 },
  tlLine: { flex: 1, width: 2, backgroundColor: colors.border, marginTop: 2 },
  tlStatus: { fontSize: 15, fontWeight: '700', color: colors.text },
  tlMeta: { fontSize: 12.5, color: colors.textMuted, marginTop: 2 },
  tlNote: { fontSize: 13, color: colors.text, marginTop: 4 },
});
