import { Ionicons } from '@expo/vector-icons';
import { Stack, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Alert, Image, Linking, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { projectApi } from '@/api/services';
import { Card, EmptyState, ErrorState, Loading, Pill, SectionTitle } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { colors, radius, spacing } from '@/theme';
import type { ProjectVideo } from '@/types/models';
import { formatDate } from '@/utils/format';

const FILE_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  pdf: 'document-text',
  jpg: 'image',
  jpeg: 'image',
  png: 'image',
  mp4: 'videocam',
  csv: 'grid',
  xls: 'grid',
  xlsx: 'grid',
};

async function openUrl(url?: string) {
  if (!url) return Alert.alert('Unavailable', 'This file does not have a public link yet.');
  await WebBrowser.openBrowserAsync(url);
}

/** Videos open in the YouTube (or other) app when installed, else the browser. */
async function openVideo(url: string) {
  try {
    await Linking.openURL(url);
  } catch {
    await WebBrowser.openBrowserAsync(url);
  }
}

export default function ProjectDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const project = useAsync(() => projectApi.get(id), [id]);

  if (project.loading) return <Loading />;
  if (project.error || !project.data) return <ErrorState message={project.error ?? ''} onRetry={project.reload} />;
  const p = project.data;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xl * 2 }}>
      <Stack.Screen options={{ title: p.name }} />

      {p.coverImageUrl ? <Image source={{ uri: p.coverImageUrl }} style={styles.heroImage} resizeMode="cover" /> : null}

      <Card>
        <View style={styles.head}>
          {p.iconUrl ? (
            <View style={styles.logo}>
              <Image source={{ uri: p.iconUrl }} style={{ width: '100%', height: '100%' }} resizeMode="contain" accessibilityLabel={`${p.name} logo`} />
            </View>
          ) : null}
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{p.name}</Text>
            {p.location ? <Text style={styles.sub}>{p.location}</Text> : null}
          </View>
        </View>
        {p.projectType ? (
          <View style={styles.tags}>
            <Pill text={p.projectType} color={colors.primary} bg={colors.primarySoft} />
          </View>
        ) : null}
        {p.description ? <Text style={styles.desc}>{p.description}</Text> : null}
        {p.configurations?.length ? (
          <View style={styles.tags}>
            {p.configurations.map((c) => (
              <Pill key={c} text={c} color={colors.primary} bg={colors.primarySoft} />
            ))}
          </View>
        ) : null}
        {p.priceRange ? <Text style={styles.price}>{p.priceRange}</Text> : null}
      </Card>

      {p.videos.length ? <SectionTitle>{`Videos (${p.videos.length})`}</SectionTitle> : null}
      {p.videos.map((v) => (
        <VideoCard key={v.id} video={v} projectName={p.name} />
      ))}

      {!p.files.length && !p.documents.length && !p.videos.length ? (
        <EmptyState
          title="No brochures yet"
          message="Documents for this project haven't been added yet. Please check back later."
          icon="folder-open-outline"
        />
      ) : null}

      {p.files.length ? <SectionTitle>{`Files (${p.files.length})`}</SectionTitle> : null}
      {p.files.length ? (
        <Card style={{ paddingVertical: spacing.sm }}>
          {p.files.map((f, i) => (
            <Row
              key={f.id}
              icon={FILE_ICONS[f.fileType] ?? 'document'}
              title={f.title}
              meta={[formatDate(f.createdDate), f.size, f.fileType].filter(Boolean).join(' • ')}
              onPress={() => openUrl(f.url)}
              onShare={() => f.url && Share.share({ message: `${p.name} – ${f.title}\n${f.url}` })}
              last={i === p.files.length - 1}
            />
          ))}
        </Card>
      ) : null}

      {p.documents.length ? <SectionTitle>{`Documents & links (${p.documents.length})`}</SectionTitle> : null}
      {p.documents.length ? (
        <Card style={{ paddingVertical: spacing.sm }}>
          {p.documents.map((d, i) => (
            <Row
              key={d.id}
              icon="reader-outline"
              title={d.name}
              onPress={() => openUrl(d.url)}
              last={i === p.documents.length - 1}
            />
          ))}
        </Card>
      ) : null}
    </ScrollView>
  );
}

function VideoCard({ video, projectName }: { video: ProjectVideo; projectName: string }) {
  const share = () => Share.share({ message: `${projectName} – ${video.title}
${video.url}` });
  return (
    <Card style={{ padding: 0, overflow: 'hidden', marginBottom: spacing.md }} onPress={() => openVideo(video.url)}>
      {video.thumbnailUrl ? (
        <View>
          <Image source={{ uri: video.thumbnailUrl }} style={styles.thumb} resizeMode="cover" accessibilityIgnoresInvertColors />
          <View style={styles.play}>
            <Ionicons name="play" size={26} color="#fff" style={{ marginLeft: 3 }} />
          </View>
        </View>
      ) : null}
      <View style={styles.videoRow}>
        {!video.thumbnailUrl ? (
          <View style={styles.rowIcon}>
            <Ionicons name="play-circle" size={22} color={colors.primary} />
          </View>
        ) : null}
        <Text style={[styles.rowTitle, { flex: 1 }]} numberOfLines={2}>
          {video.title}
        </Text>
        <Pressable onPress={share} hitSlop={10} accessibilityLabel={`Share ${video.title}`}>
          <Ionicons name="share-social-outline" size={20} color={colors.textMuted} />
        </Pressable>
      </View>
    </Card>
  );
}

function Row({
  icon,
  title,
  meta,
  onPress,
  onShare,
  last,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  meta?: string;
  onPress: () => void;
  onShare?: () => void;
  last?: boolean;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.row, !last && styles.rowBorder]}>
      <View style={styles.rowIcon}>
        <Ionicons name={icon} size={20} color={colors.primary} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        {meta ? <Text style={styles.rowMeta}>{meta}</Text> : null}
      </View>
      {onShare ? (
        <Pressable onPress={onShare} hitSlop={10} accessibilityLabel={`Share ${title}`}>
          <Ionicons name="share-social-outline" size={20} color={colors.textMuted} />
        </Pressable>
      ) : (
        <Ionicons name="open-outline" size={18} color={colors.textMuted} />
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  heroImage: { width: '100%', height: 190, borderRadius: radius.lg, marginBottom: spacing.md, backgroundColor: colors.border },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  logo: {
    width: 60,
    height: 60,
    borderRadius: 14,
    padding: 6,
    backgroundColor: '#fff',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  thumb: { width: '100%', aspectRatio: 16 / 9, backgroundColor: colors.border },
  play: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    width: 56,
    height: 56,
    marginTop: -28,
    marginLeft: -28,
    borderRadius: 28,
    backgroundColor: 'rgba(0,0,0,0.6)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.lg },
  title: { fontSize: 22, fontWeight: '800', color: colors.text },
  sub: { fontSize: 13.5, color: colors.textMuted, marginTop: 2 },
  desc: { fontSize: 14, color: colors.text, marginTop: spacing.md, lineHeight: 20 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: spacing.md },
  price: { fontSize: 15, fontWeight: '700', color: colors.text, marginTop: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: 12 },
  rowBorder: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  rowIcon: { width: 38, height: 38, borderRadius: 10, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' },
  rowTitle: { fontSize: 14.5, fontWeight: '600', color: colors.text },
  rowMeta: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
});
