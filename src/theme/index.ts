import type { EnquiryStatus } from '@/types/models';

export const colors = {
  // Brand tokens from ambujaneotia.com (--primary-color, --secondary-color, --grey-color, --border-color).
  primary: '#1C4F78',
  accent: '#F7941D',
  bg: '#F5F7FA',
  border: '#D2DEEF',
  // Derived from the brand tokens for tints and readable text.
  primaryDark: '#143A59',
  primarySoft: '#E3EDF5',
  accentSoft: '#FEF0DD',
  accentText: '#A35500',
  card: '#FFFFFF',
  text: '#14293B',
  textMuted: '#5B6B7C',
  danger: '#DC2626',
  success: '#16A34A',
  white: '#FFFFFF',
};

export const radius = { sm: 8, md: 14, lg: 20, xl: 28 };
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };

export const shadow = {
  shadowColor: '#143A59',
  shadowOpacity: 0.06,
  shadowRadius: 12,
  shadowOffset: { width: 0, height: 4 },
  elevation: 2,
};

export const statusColors: Record<EnquiryStatus, { fg: string; bg: string }> = {
  New: { fg: '#1C4F78', bg: '#E3EDF5' },
  Working: { fg: '#2F6C9C', bg: '#E6F0F8' },
  'Follow up': { fg: '#6D28D9', bg: '#EDE9FE' },
  Unanswered: { fg: '#92400E', bg: '#FEF3C7' },
  'Not Reachable': { fg: '#9A3412', bg: '#FFEDD5' },
  Nurturing: { fg: '#0E7490', bg: '#CFFAFE' },
  'Visit confirmed': { fg: '#A35500', bg: '#FEF0DD' },
  Qualified: { fg: '#15803D', bg: '#DCFCE7' },
  Unqualified: { fg: '#B91C1C', bg: '#FEE2E2' },
  DND: { fg: '#7F1D1D', bg: '#FEE2E2' },
  'No action needed': { fg: '#5B6B7C', bg: '#EEF2F6' },
};

/** Space reserved at the bottom of tab pages so content clears the floating tab bar. */
export const TAB_BAR_HEIGHT = 68;
