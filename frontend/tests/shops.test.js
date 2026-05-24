import assert from 'node:assert/strict';
import test from 'node:test';
import { formatShopMeta, normalizeShopImages } from '../src/lib/shops.js';

test('normalizeShopImages splits comma-separated image strings', () => {
  assert.deepEqual(normalizeShopImages('a.jpg,b.jpg,,c.jpg'), ['a.jpg', 'b.jpg', 'c.jpg']);
});

test('formatShopMeta builds readable metadata text', () => {
  assert.equal(formatShopMeta({ area: '徐汇', avgPrice: 88, openHours: '10:00-22:00' }), '徐汇 · 人均 ¥88 · 10:00-22:00');
});
