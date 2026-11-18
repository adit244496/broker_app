import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { enquiryApi } from '@/api/services';
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader, SearchBar, StageBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { useDebounced } from '@/hooks/useDebounced';
import { useRefreshOnFocus } from '@/hooks/useRefreshOnFocus';
import { colors, radius, spacing, TAB_BAR_HEIGHT } from '@/theme';
import { isConverted } from '@/types/models';
import { inOrder, LEAD_STATUS_ORDER, OPPORTUNITY_STAGES, shownStatus } from '@/utils/brokerStage';
import { formatDate } from '@/utils/format';

type View_ = 'leads' | 'opportunities';
type Filter = string; // 'All', or a status the broker sees

export function EnquiriesTab() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  // Leads still being worked on, or leads Salesforce has converted into Opportunities.
  const [view, setView] = useState<View_>('leads');
  const [filter, setFilter] = useState<Filter>('All');
  const q = useDebounced(search);
  const enquiries = useAsync(() => enquiryApi.list(q), [q]);

  useRefreshOnFocus(enquiries.silentReload);

  const leads = useMemo(() => enquiries.data?.filter((e) => !isConverted(e)), [enquiries.data]);
  const opportunities = useMemo(() => enquiries.data?.filter(isConverted), [enquiries.data]);
  const inView = view === 'leads' ? leads : opportunities;
  const visible = useMemo(
    () => (filter === 'All' ? inView : inView?.filter((e) => shownStatus(e) === filter)),
    [inView, filter],
  );

  // Lead statuses under Leads, Opportunity stages under Opportunities; only the ones something is in.
  const counts = new Map<string, number>();
  for (const e of inView ?? []) {
    const s = shownStatus(e);
    if (s) counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  const order = view === 'leads' ? LEAD_STATUS_ORDER : OPPORTUNITY_STAGES;
  const chips: Filter[] = ['All', ...inOrder([...counts.keys(), ...(filter !== 'All' ? [filter] : [])], order)];

  const switchTo = (v: View_) => {
    setView(v);
    setFilter('All');
  };

  return (
    <View style={{ flex: 1 }}>
      <PageHeader
        title={view === 'leads' ? 'Leads' : 'Opportunities'}
        subtitle={inView ? `${inView.length} total` : undefined}
        right={<Button title="Create" icon="add" onPress={() => router.push('/enquiries/new')} style={{ height: 40 }} />}
      />

      <View style={styles.toggle}>
        {(
          [
            ['leads', 'Leads', leads?.length],
            ['opportunities', 'Opportunities', opportunities?.length],
          ] as const
        ).map(([key, label, count]) => {
          const active = view === key;
          return (
            <Pressable
              key={key}
              onPress={() => switchTo(key)}
              style={[styles.toggleItem, active && styles.toggleActive]}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
            >
              <Text style={[styles.toggleText, active && styles.toggleTextActive]}>
                {label}
                {count !== undefined ? ` (${count})` : ''}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <SearchBar value={search} onChangeText={setSearch} placeholder="Search by customer, mobile or ID" />

      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters}>
          {chips.map((st) => {
            const active = st === filter;
            const count = st === 'All' ? inView?.length : (counts.get(st) ?? 0);
            return (
              <Pressable key={st} onPress={() => setFilter(st)} style={[styles.filter, active && styles.filterActive]}>
                <Text style={[styles.filterText, active && { color: colors.white }]}>
                  {st}
                  {count !== undefined ? ` (${count})` : ''}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {enquiries.loading && !enquiries.data ? (
        <Loading />
      ) : enquiries.error && !enquiries.data ? (
        <ErrorState message={enquiries.error} onRetry={enquiries.reload} />
      ) : (
        <FlatList
          data={visible}
          keyExtractor={(e) => e.id}
          contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: TAB_BAR_HEIGHT + 48, gap: spacing.md }}
          refreshControl={<RefreshControl refreshing={enquiries.refreshing} onRefresh={enquiries.refresh} />}
          ListEmptyComponent={
            view === 'leads' ? (
              <EmptyState
                icon="chatbubbles-outline"
                title="No leads found"
                message={filter === 'All' && !q ? 'Create a lead to start tracking it here.' : undefined}
              />
            ) : (
              <EmptyState
                icon="trophy-outline"
                title="No opportunities yet"
                message={filter === 'All' && !q ? 'Leads move here once Ambuja Neotia converts them into opportunities.' : undefined}
              />
            )
          }
          renderItem={({ item: e }) => (
            <Card
              onPress={() => router.push({ pathname: '/enquiries/[id]', params: { id: e.id } })}
              style={view === 'opportunities' ? styles.converted : undefined}
            >
              <View style={styles.top}>
                <Text style={styles.number}>{e.enquiryNumber}</Text>
                {shownStatus(e) ? <StageBadge stage={shownStatus(e)!} /> : null}
              </View>
              <Text style={styles.name}>
                {e.firstName} {e.lastName}
              </Text>
              <View style={styles.metaRow}>
                <Meta icon="business-outline" text={e.projectName ?? '—'} />
                <Meta icon="call-outline" text={e.mobile} />
              </View>
              <View style={styles.metaRow}>
                <Meta icon="person-outline" text={e.brokerName ?? '—'} />
                <Meta icon="time-outline" text={formatDate(e.createdDate)} />
              </View>
            </Card>
          )}
        />
      )}
    </View>
  );
}

function Meta({ icon, text }: { icon: keyof typeof Ionicons.glyphMap; text: string }) {
  return (
    <View style={styles.meta}>
      <Ionicons name={icon} size={14} color={colors.textMuted} />
      <Text style={styles.metaText} numberOfLines={1}>
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  toggle: {
    flexDirection: 'row',
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    padding: 4,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  toggleItem: { flex: 1, paddingVertical: 9, borderRadius: radius.sm + 2, alignItems: 'center' },
  toggleActive: { backgroundColor: colors.primary },
  toggleText: { fontSize: 14, fontWeight: '700', color: colors.textMuted },
  toggleTextActive: { color: colors.white },
  filters: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, gap: spacing.sm },
  filter: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  filterActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterText: { fontSize: 12.5, fontWeight: '600', color: colors.text },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  converted: { borderLeftWidth: 4, borderLeftColor: colors.success },
  number: { fontSize: 12, fontWeight: '700', color: colors.textMuted },
  name: { fontSize: 16, fontWeight: '700', color: colors.text, marginTop: spacing.sm },
  metaRow: { flexDirection: 'row', gap: spacing.md, marginTop: 6 },
  meta: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 5 },
  metaText: { fontSize: 13, color: colors.text, flex: 1 },
});
