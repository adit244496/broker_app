import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { FlatList, Image, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { projectApi } from '@/api/services';
import { Card, EmptyState, ErrorState, Loading, PageHeader, Pill } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { colors, radius, spacing, TAB_BAR_HEIGHT } from '@/theme';

export function ProjectsTab() {
  const router = useRouter();
  const projects = useAsync(() => projectApi.list());

  return (
    <View style={{ flex: 1 }}>
      <PageHeader title="Brochures" subtitle="Project documents & marketing collateral" />
      {projects.loading && !projects.data ? (
        <Loading />
      ) : projects.error && !projects.data ? (
        <ErrorState message={projects.error} onRetry={projects.reload} />
      ) : (
        <FlatList
          data={projects.data}
          keyExtractor={(p) => p.id}
          contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: TAB_BAR_HEIGHT + 48, gap: spacing.lg }}
          refreshControl={<RefreshControl refreshing={projects.refreshing} onRefresh={projects.refresh} />}
          ListEmptyComponent={<EmptyState icon="business-outline" title="No projects available" />}
          renderItem={({ item: p }) => (
            <Card style={{ padding: 0, overflow: 'hidden' }} onPress={() => router.push({ pathname: '/projects/[id]', params: { id: p.id } })}>
              <View>
                {p.coverImageUrl ? (
                  <Image source={{ uri: p.coverImageUrl }} style={styles.cover} resizeMode="cover" />
                ) : (
                  <View style={[styles.cover, styles.coverPlaceholder]}>
                    {p.iconUrl ? null : <Ionicons name="business" size={40} color="rgba(255,255,255,0.9)" />}
                  </View>
                )}
                {p.iconUrl ? (
                  <View style={styles.iconWrap}>
                    <Image source={{ uri: p.iconUrl }} style={styles.icon} resizeMode="contain" accessibilityLabel={`${p.name} logo`} />
                  </View>
                ) : null}
                {p.videos.length ? (
                  <View style={styles.videoBadge}>
                    <Ionicons name="play" size={12} color="#fff" />
                    <Text style={styles.videoBadgeText}>{p.videos.length === 1 ? 'Video' : `${p.videos.length} videos`}</Text>
                  </View>
                ) : null}
              </View>
              <View style={{ padding: spacing.lg, paddingTop: p.iconUrl ? spacing.lg + 24 : spacing.lg }}>
                <Text style={styles.name}>{p.name}</Text>
                {p.projectType ? (
                  <View style={styles.tags}>
                    <Pill text={p.projectType} color={colors.primary} bg={colors.primarySoft} />
                  </View>
                ) : null}
                {p.location ? (
                  <View style={styles.loc}>
                    <Ionicons name="location-outline" size={14} color={colors.textMuted} />
                    <Text style={styles.locText}>{p.location}</Text>
                  </View>
                ) : null}
                {p.configurations?.length ? (
                  <View style={styles.tags}>
                    {p.configurations.map((c) => (
                      <Pill key={c} text={c} color={colors.primary} bg={colors.primarySoft} />
                    ))}
                  </View>
                ) : null}
                <View style={styles.footer}>
                  <Text style={styles.price}>{p.priceRange ?? ''}</Text>
                  <Text style={styles.counts}>{materialsLabel(p.documents.length + p.files.length, p.videos.length)}</Text>
                </View>
              </View>
            </Card>
          )}
        />
      )}
    </View>
  );
}

/** "2 videos · 3 documents", "1 document", or a note that brochures are still to come. */
function materialsLabel(docs: number, videos: number) {
  const parts = [
    videos ? `${videos} video${videos === 1 ? '' : 's'}` : '',
    docs ? `${docs} document${docs === 1 ? '' : 's'}` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Brochures coming soon';
}

const styles = StyleSheet.create({
  cover: { height: 140, width: '100%', borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg },
  coverPlaceholder: { backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  // The logo sits on a white tile over the cover's bottom-left corner.
  iconWrap: {
    position: 'absolute',
    left: spacing.lg,
    bottom: -24,
    width: 56,
    height: 56,
    borderRadius: 14,
    backgroundColor: '#fff',
    padding: 6,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  icon: { width: '100%', height: '100%' },
  videoBadge: {
    position: 'absolute',
    right: spacing.md,
    top: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  videoBadgeText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  name: { fontSize: 18, fontWeight: '800', color: colors.text },
  loc: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4 },
  locText: { fontSize: 13, color: colors.textMuted },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: spacing.md },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: spacing.md },
  price: { fontSize: 14, fontWeight: '700', color: colors.text },
  counts: { fontSize: 12.5, color: colors.textMuted },
});
