import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import type { ComponentRef, RefObject } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, TAB_BAR_HEIGHT } from '@/theme';

export interface TabItem {
  key: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
}

interface Props {
  tabs: TabItem[];
  activeIndex: number;
  onTabPress: (index: number) => void;
  /** Android only: the BlurTargetView whose content this bar blurs. */
  blurTarget: RefObject<ComponentRef<typeof View> | null>;
}

/** Floating frosted-glass bottom tab bar. */
export function GlassTabBar({ tabs, activeIndex, onTabPress, blurTarget }: Props) {
  const insets = useSafeAreaInsets();

  return (
    <View pointerEvents="box-none" style={[styles.wrapper, { bottom: Math.max(insets.bottom, 12) }]}>
      <BlurView
        intensity={Platform.OS === 'ios' ? 60 : 40}
        tint="systemUltraThinMaterialLight"
        blurMethod="dimezisBlurViewSdk31Plus"
        blurTarget={blurTarget}
        style={styles.bar}
      >
        {/* Glossy highlight across the top half of the glass */}
        <View pointerEvents="none" style={styles.gloss} />
        {tabs.map((tab, i) => {
          const active = i === activeIndex;
          return (
            <Pressable
              key={tab.key}
              onPress={() => onTabPress(i)}
              style={styles.tab}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              accessibilityLabel={tab.label}
            >
              <View style={[styles.iconPill, active && styles.iconPillActive]}>
                <Ionicons name={active ? tab.activeIcon : tab.icon} size={22} color={active ? colors.white : colors.text} />
              </View>
              <Text style={[styles.label, active && styles.labelActive]} numberOfLines={1}>
                {tab.label}
              </Text>
            </Pressable>
          );
        })}
      </BlurView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { position: 'absolute', left: 14, right: 14 },
  bar: {
    height: TAB_BAR_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 30,
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth * 2,
    borderColor: 'rgba(255,255,255,0.7)',
    // Translucent fill keeps the bar readable where blur is unavailable (Android < 12).
    backgroundColor: Platform.OS === 'android' ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.25)',
  },
  gloss: {
    ...StyleSheet.absoluteFill,
    bottom: '50%',
    backgroundColor: 'rgba(255,255,255,0.28)',
  },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 2 },
  iconPill: { paddingHorizontal: 14, paddingVertical: 4, borderRadius: 16 },
  iconPillActive: { backgroundColor: colors.primary },
  label: { fontSize: 10.5, color: colors.text, fontWeight: '500' },
  labelActive: { color: colors.primary, fontWeight: '700' },
});
