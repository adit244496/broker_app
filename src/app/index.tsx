import { BlurTargetView } from "expo-blur";
import { memo, useMemo, useRef, useState, type ComponentRef } from "react";
import { StyleSheet, View } from "react-native";
import PagerView from "react-native-pager-view";
import { SafeAreaView } from "react-native-safe-area-context";
import { GlassTabBar, type TabItem } from "@/components/GlassTabBar";
import { DashboardTab } from "@/features/tabs/DashboardTab";
import { EnquiriesTab } from "@/features/tabs/EnquiriesTab";
import { LeadsLinkContext, type LeadsRequest } from "@/features/tabs/LeadsLink";
import { ProfileTab } from "@/features/tabs/ProfileTab";
import { ProjectsTab } from "@/features/tabs/ProjectsTab";
import { colors } from "@/theme";

const TABS: (TabItem & { Component: React.ComponentType })[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    icon: "grid-outline",
    activeIcon: "grid",
    Component: memo(DashboardTab),
  },
  {
    key: "enquiries",
    label: "Leads",
    icon: "chatbubbles-outline",
    activeIcon: "chatbubbles",
    Component: memo(EnquiriesTab),
  },
  {
    key: "projects",
    label: "Brochures",
    icon: "book-outline",
    activeIcon: "book",
    Component: memo(ProjectsTab),
  },
  {
    key: "profile",
    label: "Profile",
    icon: "person-circle-outline",
    activeIcon: "person-circle",
    Component: memo(ProfileTab),
  },
];

/** Home shell: swipeable pages with a floating frosted-glass tab bar. */
export default function Home() {
  const pagerRef = useRef<PagerView>(null);
  const blurTargetRef = useRef<ComponentRef<typeof View> | null>(null);
  const [index, setIndex] = useState(0);

  const goTo = (i: number) => {
    setIndex(i);
    pagerRef.current?.setPage(i);
  };
  const [leadsRequest, setLeadsRequest] = useState<LeadsRequest>();
  const leadsLink = useMemo(
    () => ({
      activeTab: TABS[index]?.key,
      request: leadsRequest,
      openLeads: (view: LeadsRequest["view"], filter = "All") => {
        setLeadsRequest({ view, filter, nonce: Date.now() });
        const i = TABS.findIndex((t) => t.key === "enquiries");
        setIndex(i);
        pagerRef.current?.setPage(i);
      },
    }),
    [leadsRequest, index],
  );

  return (
    <LeadsLinkContext.Provider value={leadsLink}>
      <View style={styles.root}>
        {/* Everything inside the target is what the tab bar blurs on Android. */}
        <BlurTargetView ref={blurTargetRef} style={StyleSheet.absoluteFill}>
          <View style={[styles.blob, styles.blobA]} />
          <View style={[styles.blob, styles.blobB]} />
          <SafeAreaView edges={["top"]} style={{ flex: 1 }}>
            <PagerView
              ref={pagerRef}
              style={{ flex: 1 }}
              initialPage={0}
              onPageSelected={(e) => setIndex(e.nativeEvent.position)}
              offscreenPageLimit={1}
            >
              {TABS.map(({ key, Component }) => (
                <View key={key} style={{ flex: 1 }} collapsable={false}>
                  <Component />
                </View>
              ))}
            </PagerView>
          </SafeAreaView>
        </BlurTargetView>

        <GlassTabBar
          tabs={TABS}
          activeIndex={index}
          onTabPress={goTo}
          blurTarget={blurTargetRef}
        />
      </View>
    </LeadsLinkContext.Provider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  // Soft color washes give the frosted glass something to refract.
  blob: {
    position: "absolute",
    width: 320,
    height: 320,
    borderRadius: 160,
    opacity: 0.18,
  },
  blobA: { backgroundColor: colors.primary, top: -120, right: -100 },
  blobB: { backgroundColor: colors.accent, bottom: -60, left: -120 },
});
