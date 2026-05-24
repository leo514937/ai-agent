import assert from 'node:assert/strict';
import test from 'node:test';
import { buildNavItems, resolveRouteTitle } from '../src/lib/navigation.js';

test('buildNavItems exposes the direct service pages in order', () => {
  assert.deepEqual(
    buildNavItems().map((item) => item.path),
    ['/', '/shops', '/blogs', '/ai', '/me'],
  );
});

test('resolveRouteTitle returns a friendly title for nested pages', () => {
  assert.equal(resolveRouteTitle('/shops/12'), '商铺详情');
  assert.equal(resolveRouteTitle('/blogs/33'), '博客详情');
  assert.equal(resolveRouteTitle('/ai'), 'AI 助手');
});
