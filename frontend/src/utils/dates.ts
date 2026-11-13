import { parseISO } from 'date-fns';

/** Format API calendar dates and timestamps for display. */
export const formatDate = (
  value: string,
  options?: Intl.DateTimeFormatOptions,
  locale?: string,
): string => parseISO(value).toLocaleDateString(locale, options);
