export const PREPARATION_FAILED = 'PREPARATION_FAILED';
export const TRIAL_CAPACITY_UNAVAILABLE = 'TRIAL_CAPACITY_UNAVAILABLE';

export const TRIAL_NOT_ELIGIBLE = 'TRIAL_NOT_ELIGIBLE';

export function extractionErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'code' in detail &&
      detail.code === TRIAL_NOT_ELIGIBLE && 'message' in detail && typeof detail.message === 'string') {
    return detail.message;
  }
  return fallback;
}
