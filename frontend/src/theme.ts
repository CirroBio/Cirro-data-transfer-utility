/**
 * Cirro design tokens, ported so this tool reads as part of the platform.
 *
 * Copied from Cirro-components `packages/ui/src/theme/theme.ts` (the `Light`
 * theme) rather than imported: `@cirrobio/ui` is an unpublished private package
 * whose peer deps require React 19 and two commercially licensed MUI X
 * packages. Only the tokens this app actually uses are carried over. When the
 * upstream palette changes, re-copy from that file.
 */
import { alpha, createTheme } from "@mui/material/styles";

export const COLOR_BORDER = "#e0e0e0";
export const COLOR_PRIMARY = "#050b26";
export const COLOR_PRIMARY_LIGHT = "#5C5D73";
export const COLOR_LOGO_LIGHT = "#24bfd3";
export const COLOR_SECONDARY = "#0e7ca0";
export const COLOR_MUTED = "#6b6b6b";
export const COLOR_WHITE = "#FFF";
export const COLOR_BACKGROUND = "#fafbfc";
export const COLOR_GRAY = "#f2f7f8";
export const COLOR_WARNING = "#894073";
export const COLOR_ERROR = "#D64545";
export const COLOR_SUCCESS = "#2E7D55";

export const HOVER_BG = alpha(COLOR_SECONDARY, 0.08);
export const HOVER_TRANSITION = "background-color 150ms ease-in-out";

export const FONT_MONO =
  '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, "Roboto Mono", monospace';

/** Eyebrow heading shared by the page title and every panel header. */
export const monoHeadingSx = {
  fontFamily: "inherit",
  fontSize: 14,
  letterSpacing: "0.04em",
  fontWeight: 400,
  color: COLOR_SECONDARY,
} as const;

/** Card chrome from upstream's Panel: white, hairline border, 10px radius. */
export const PANEL_RADIUS = "10px";

/** Dot colour per Cirro auth state, shared by the banner and the settings page. */
export const AUTH_STATUS_COLOR: Record<string, string> = {
  connected: COLOR_SUCCESS,
  pending: COLOR_WARNING,
  error: COLOR_ERROR,
  disconnected: COLOR_MUTED,
};

export const theme = createTheme({
  palette: {
    primary: { main: COLOR_PRIMARY, light: COLOR_PRIMARY_LIGHT },
    secondary: { main: COLOR_SECONDARY, light: COLOR_WHITE },
    warning: { main: COLOR_WARNING },
    error: { main: COLOR_ERROR },
    success: { main: COLOR_SUCCESS },
    background: { default: COLOR_BACKGROUND, paper: COLOR_WHITE },
    divider: COLOR_BORDER,
    action: { hover: HOVER_BG, hoverOpacity: 0.08 },
  },
  typography: {
    fontFamily: '"Geist", "-apple-system", "BlinkMacSystemFont", sans-serif',
    fontSize: 18,
    fontWeightRegular: 400,
    fontWeightBold: 800,
    body1: { fontSize: ".8rem", lineHeight: 1.5, letterSpacing: 0, color: COLOR_PRIMARY },
    body2: { fontSize: ".8rem", lineHeight: 1.5, letterSpacing: 0, color: COLOR_PRIMARY_LIGHT },
    h3: { fontSize: "1.2rem", lineHeight: 1.2, color: COLOR_SECONDARY },
    h4: { fontSize: "1rem", lineHeight: 1.5, color: COLOR_SECONDARY },
    h5: { fontSize: ".8rem", lineHeight: 1, color: COLOR_SECONDARY },
    h6: { fontSize: ".8rem", lineHeight: 1.2, color: COLOR_PRIMARY },
    subtitle2: { fontSize: ".8rem" },
    caption: { fontSize: ".8rem" },
  },
  components: {
    MuiAppBar: {
      styleOverrides: {
        root: { backgroundColor: COLOR_PRIMARY, boxShadow: "none" },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          fontSize: "12.8px",
          fontFamily: "inherit",
          textTransform: "none",
          fontWeight: 400,
          cursor: "pointer",
          color: COLOR_PRIMARY,
        },
        startIcon: { color: COLOR_SECONDARY },
        containedPrimary: { color: COLOR_WHITE },
        containedSecondary: { color: COLOR_WHITE },
      },
    },
    MuiChip: {
      styleOverrides: { root: { fontSize: ".8rem" } },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: PANEL_RADIUS,
          backgroundColor: COLOR_WHITE,
          padding: 0,
        },
      },
    },
    MuiCardHeader: {
      styleOverrides: {
        root: { backgroundColor: COLOR_WHITE, paddingTop: 12, paddingBottom: 12 },
      },
    },
    MuiTooltip: {
      defaultProps: { arrow: true },
      styleOverrides: {
        tooltip: {
          backgroundColor: COLOR_WHITE,
          color: COLOR_PRIMARY,
          fontSize: 11,
          border: `1px solid ${COLOR_SECONDARY}`,
          boxShadow: "0px 2px 8px rgba(0, 0, 0, 0.15)",
        },
        arrow: {
          color: COLOR_WHITE,
          "&::before": {
            border: `1px solid ${COLOR_SECONDARY}`,
            backgroundColor: COLOR_WHITE,
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: "5px" },
        standardInfo: { backgroundColor: COLOR_GRAY },
      },
    },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontSize: ".8rem",
          borderBottomColor: COLOR_BORDER,
          paddingTop: 8,
          paddingBottom: 8,
        },
        head: { color: COLOR_SECONDARY, fontWeight: 400 },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          transition: HOVER_TRANSITION,
          "&:hover": { backgroundColor: HOVER_BG },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: COLOR_GRAY, height: 8, borderRadius: 999 },
        bar: { backgroundColor: COLOR_SECONDARY },
      },
    },
  },
});
