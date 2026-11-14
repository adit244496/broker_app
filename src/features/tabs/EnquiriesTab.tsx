import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { enquiryApi } from '@/api/services';
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader, SearchBar, StatusBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { useDebounced } from '@/hooks/useDebounced';
import { useRefreshOnFocus } from '@/hooks/useRefreshOnFocus';
import { colors, spacing, TAB_BAR_HEIGHT } from '@/theme';
import { ENQUIRY_STATUSES, type EnquiryStatus } from '@/types/models';
import { formatDate } from '@/utils/format';

export function EnquiriesTab() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<EnquiryStatus | 'All'>('All');
  const q = useDebounced(search);
  const enquiries = useAsync(() => enquiryApi.list(q), [q]);

  useRefreshOnFocus(enquiries.silentReload);

  const visible = useMemo(
    () => (filter === 'All' ? enquiries.data : enquiries.data?.filter((e) => e.status === filter)),
    [enquiries.data, filter],
  );

  return (
    <View style={{ flex: 1 }}>
      <PageHeader
        title="Leads"
        subtitle={enquiries.data ? `${enquiries.data.length} total` : undefined}
        right={<Button title="Create" icon="add" onPress={() => router.push('/enquiries/new')} style={{ height: 40 }} />}
      />
      <SearchBar value={search} onChangeText={setSearch} placeholder="Search by customer, mobile or ID" />

      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters}>
          {(['All', ...ENQUIRY_STATUSES] as const).map((st) => {
            const active = st === filter;
            const count = st === 'All' ? enquiries.data?.length : enquiries.data?.filter((e) => e.status === st).length;
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
            <EmptyState
              icon="chatbubbles-outline"
              title="No leads found"
              message={filter === 'All' && !q ? 'Create a lead to start tracking it here.' : undefined}
            />
          }
          renderItem={({ item: e }) => (
            <Card onPress={() => router.push({ pathname: '/enquiries/[id]', params: { id: e.id } })}>
              <View style={styles.top}>
                <Text style={styles.number}>{e.enquiryNumber}</Text>
                <StatusBadge status={e.status} />
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
  filters: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, gap: spacing.sm },
  filter: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  filterActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterText: { fontSize: 12.5, fontWeight: '600', color: colors.text },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  number: { fontSize: 12, fontWeight: '700', color: colors.textMuted },
  name: { fontSize: 16, fontWeight: '700', color: colors.text, marginTop: spacing.sm },
  metaRow: { flexDirection: 'row', gap: spacing.md, marginTop: 6 },
  meta: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 5 },
  metaText: { fontSize: 13, color: colors.text, flex: 1 },
});
