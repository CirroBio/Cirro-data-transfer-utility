import { Card, CardHeader, Chip, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { COLOR_BORDER, monoHeadingSx } from "../theme";

interface Props {
  title: string;
  /** Rendered as a chip beside the title — used for row counts. */
  count?: number;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

/** The titled card shell, matching Cirro-components' Panel chrome: white card,
 *  hairline border, 10px radius, mono eyebrow title. */
export default function Panel({ title, count, subtitle, actions, children }: Props) {
  return (
    <Card variant="outlined" sx={{ mb: 2.5, borderColor: COLOR_BORDER }}>
      <CardHeader
        sx={{ px: 3, borderBottom: `1px solid ${COLOR_BORDER}` }}
        title={
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography component="h2" sx={monoHeadingSx}>
              {title.toUpperCase()}
            </Typography>
            {count !== undefined && (
              <Chip label={count} size="small" sx={{ height: 20, fontSize: 11 }} />
            )}
            {subtitle && (
              <Typography variant="body2" sx={{ pl: 1 }}>
                {subtitle}
              </Typography>
            )}
          </Stack>
        }
        action={actions}
      />
      {children}
    </Card>
  );
}
