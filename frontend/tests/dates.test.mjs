import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { formatDate } from '../src/utils/dates.ts';

const originalTZ = process.env.TZ;
after(() => {
  if (originalTZ === undefined) delete process.env.TZ;
  else process.env.TZ = originalTZ;
});

for (const timeZone of ['UTC', 'America/Toronto', 'Pacific/Honolulu', 'Asia/Kolkata']) {
  test(`calendar dates retain their day in ${timeZone}`, () => {
    process.env.TZ = timeZone;
    assert.equal(formatDate('2003-12-31', undefined, 'en-US'), '12/31/2003');
    assert.equal(formatDate('2024-02-29', undefined, 'en-US'), '2/29/2024');
    assert.equal(formatDate('2026-01-01', {
      year: 'numeric', month: 'long', day: 'numeric',
    }, 'en-US'), 'January 1, 2026');
  });

  test(`timestamps still use local time in ${timeZone}`, () => {
    process.env.TZ = timeZone;
    const timestamp = '2026-01-01T00:30:00Z';
    assert.equal(formatDate(timestamp, undefined, 'en-US'),
      new Date(timestamp).toLocaleDateString('en-US'));
  });
}
