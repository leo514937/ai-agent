# Vue User Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Vue 3 frontend for the existing Spring Boot backend, covering the user home, shop, blog, profile, coupon, and AI assistant experiences with a dark cyan-accented visual style inspired by the reference project.

**Architecture:** Create a standalone `frontend/` Vite app that talks to `http://127.0.0.1:8081` through a dev-server proxy. Keep page-level logic in `src/pages`, shared UI in `src/components`, and API/session helpers in `src/lib` so the UI stays modular and easy to extend. Favor data-driven rendering with graceful empty and guest states because some backend endpoints are public while others should degrade cleanly when no login token is present.

**Tech Stack:** Vue 3, Vite, Vue Router, native `fetch`, CSS variables and handcrafted layout styles, Node `node --test` for a small set of utility tests.

---

### Task 1: Scaffold the Vue app and API helpers

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/lib/http.js`
- Create: `frontend/src/lib/storage.js`
- Create: `frontend/tests/http.test.js`

- [ ] **Step 1: Write the failing test**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { unwrapResult, joinApiUrl } from '../src/lib/http.js';

test('unwrapResult returns data on success and throws on failure', () => {
  assert.deepEqual(unwrapResult({ success: true, data: { id: 1 } }), { id: 1 });
  assert.throws(() => unwrapResult({ success: false, errorMsg: 'boom' }), /boom/);
});

test('joinApiUrl normalizes leading and trailing slashes', () => {
  assert.equal(joinApiUrl('/shop/', '/of/type'), '/shop/of/type');
  assert.equal(joinApiUrl('shop', 'of/name'), '/shop/of/name');
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && node --test tests/http.test.js`

Expected: FAIL because `src/lib/http.js` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```js
export function joinApiUrl(basePath, path) {
  const cleanBase = `/${String(basePath || '').replace(/^\/+|\/+$/g, '')}`;
  const cleanPath = String(path || '').replace(/^\/+/, '');
  return `${cleanBase}/${cleanPath}`.replace(/\/+/g, '/');
}

export function unwrapResult(payload) {
  if (!payload || payload.success !== true) {
    throw new Error(payload?.errorMsg || '请求失败');
  }
  return payload.data;
}
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && node --test tests/http.test.js`

Expected: PASS with no stack traces.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/vite.config.js frontend/index.html frontend/src/main.js frontend/src/App.vue frontend/src/styles.css frontend/src/lib/http.js frontend/src/lib/storage.js frontend/tests/http.test.js
git commit -m "feat: scaffold vue frontend"
```

### Task 2: Build the app shell, routing, and navigation

**Files:**
- Create: `frontend/src/router/index.js`
- Create: `frontend/src/layouts/AppShell.vue`
- Create: `frontend/src/components/AppHeader.vue`
- Create: `frontend/src/components/AppNav.vue`
- Create: `frontend/src/components/SectionTitle.vue`
- Create: `frontend/src/components/StatCard.vue`
- Create: `frontend/src/lib/navigation.js`
- Create: `frontend/tests/navigation.test.js`
- Create: `frontend/src/pages/HomePage.vue`
- Create: `frontend/src/pages/NotFoundPage.vue`

- [ ] **Step 1: Write the failing test**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildNavItems, resolveRouteTitle } from '../src/lib/navigation.js';

test('buildNavItems exposes the main user pages in order', () => {
  assert.deepEqual(
    buildNavItems().map((item) => item.path),
    ['/', '/shops', '/blogs', '/ai', '/me'],
  );
});

test('resolveRouteTitle returns a friendly title', () => {
  assert.equal(resolveRouteTitle('/shops/12'), '商铺详情');
  assert.equal(resolveRouteTitle('/ai'), 'AI 助手');
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && node --test tests/navigation.test.js`

Expected: FAIL because `src/lib/navigation.js` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```js
export function buildNavItems() {
  return [
    { path: '/', label: '首页' },
    { path: '/shops', label: '商铺' },
    { path: '/blogs', label: '博客' },
    { path: '/ai', label: 'AI 助手' },
    { path: '/me', label: '我的' },
  ];
}

export function resolveRouteTitle(pathname) {
  if (/^\/shops\/\d+/.test(pathname)) return '商铺详情';
  if (/^\/blogs\/\d+/.test(pathname)) return '博客详情';
  if (pathname === '/ai') return 'AI 助手';
  if (pathname === '/me') return '个人中心';
  return '首页';
}
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && node --test tests/navigation.test.js`

Expected: PASS.

- [ ] **Step 5: Implement shell rendering**

Use the new router plus `AppShell.vue` to render:
`顶部品牌栏 -> 左侧/底部导航 -> 中间内容区 -> 右侧信息栏（桌面）`
and keep the shell responsive so mobile only shows the bottom navigation.

### Task 3: Implement shop and voucher pages

**Files:**
- Create: `frontend/src/pages/ShopPage.vue`
- Create: `frontend/src/pages/ShopDetailPage.vue`
- Create: `frontend/src/components/ShopCard.vue`
- Create: `frontend/src/components/VoucherCard.vue`
- Create: `frontend/src/components/EmptyState.vue`
- Create: `frontend/src/lib/shops.js`
- Create: `frontend/tests/shops.test.js`

- [ ] **Step 1: Write the failing test**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { formatShopMeta, normalizeShopImages } from '../src/lib/shops.js';

test('normalizeShopImages splits comma-separated image strings', () => {
  assert.deepEqual(normalizeShopImages('a.jpg,b.jpg,,c.jpg'), ['a.jpg', 'b.jpg', 'c.jpg']);
});

test('formatShopMeta builds readable metadata text', () => {
  assert.equal(formatShopMeta({ area: '徐汇', avgPrice: 88, openHours: '10:00-22:00' }), '徐汇 · 人均 ¥88 · 10:00-22:00');
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && node --test tests/shops.test.js`

Expected: FAIL because `src/lib/shops.js` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```js
export function normalizeShopImages(images) {
  return String(images || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatShopMeta(shop) {
  const parts = [];
  if (shop?.area) parts.push(shop.area);
  if (shop?.avgPrice) parts.push(`人均 ¥${shop.avgPrice}`);
  if (shop?.openHours) parts.push(shop.openHours);
  return parts.join(' · ');
}
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && node --test tests/shops.test.js`

Expected: PASS.

- [ ] **Step 5: Build the shop views**

Render:
- 分类横条
- 商铺列表卡片
- 商铺详情头图、评分、地址、营业时间
- 优惠券列表与秒杀入口
- 没有数据时的空状态

### Task 4: Implement blog and user center

**Files:**
- Create: `frontend/src/pages/BlogPage.vue`
- Create: `frontend/src/pages/BlogDetailPage.vue`
- Create: `frontend/src/pages/MePage.vue`
- Create: `frontend/src/components/BlogCard.vue`
- Create: `frontend/src/components/ProfileCard.vue`
- [ ] **Step 1: Build the blog feed and detail page**

Render:
- 热门博客和关注流
- 作者头像、点赞数、评论数、发布时间
- 博客详情页的长文阅读体验
- 点赞和查看作者信息入口

- [ ] **Step 2: Build the user center as a direct service page**

Render:
- 用户头像和昵称
- 今日签到状态和连续签到天数
- 常用入口卡片
- 关注、收藏、最近浏览等示意内容
- 没有登录时的游客态说明，而不是单独登录页

### Task 5: Implement the AI assistant console

**Files:**
- Create: `frontend/src/pages/AiPage.vue`
- Create: `frontend/src/components/assistant/AssistantHistory.vue`
- Create: `frontend/src/components/assistant/AssistantComposer.vue`
- Create: `frontend/src/components/assistant/AssistantContextRail.vue`
- Create: `frontend/src/components/assistant/AssistantMessage.vue`
- Create: `frontend/src/lib/assistant.js`
- Create: `frontend/tests/assistant.test.js`

- [ ] **Step 1: Write the failing test**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeAssistantResponse, buildAssistantMessagePayload } from '../src/lib/assistant.js';

test('normalizeAssistantResponse keeps suggestions and cards arrays', () => {
  const response = normalizeAssistantResponse({
    answer: 'hello',
    suggestions: [{ label: '看优惠券', prompt: '看优惠券' }],
    shops: [{ id: 1, name: '店铺A' }],
    vouchers: [{ id: 2, title: '券A' }],
  });
  assert.equal(response.answer, 'hello');
  assert.equal(response.suggestions.length, 1);
  assert.equal(response.shops.length, 1);
  assert.equal(response.vouchers.length, 1);
});

test('buildAssistantMessagePayload includes page and context', () => {
  assert.deepEqual(
    buildAssistantMessagePayload('推荐附近火锅', { page: 'shops', shopId: 12 }),
    { message: '推荐附近火锅', page: 'shops', context: { shopId: 12 } },
  );
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && node --test tests/assistant.test.js`

Expected: FAIL because `src/lib/assistant.js` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```js
export function normalizeAssistantResponse(payload) {
  return {
    answer: payload?.answer || '',
    mode: payload?.mode || 'faq',
    source: payload?.source || 'local',
    fallback: Boolean(payload?.fallback),
    page: payload?.page || 'assistant',
    currentTopic: payload?.currentTopic || '',
    suggestions: Array.isArray(payload?.suggestions) ? payload.suggestions : [],
    shops: Array.isArray(payload?.shops) ? payload.shops : [],
    vouchers: Array.isArray(payload?.vouchers) ? payload.vouchers : [],
    cards: Array.isArray(payload?.cards) ? payload.cards : [],
    nextSteps: Array.isArray(payload?.nextSteps) ? payload.nextSteps : [],
    taskChain: Array.isArray(payload?.taskChain) ? payload.taskChain : [],
    context: payload?.context || {},
  };
}

export function buildAssistantMessagePayload(message, context = {}) {
  return {
    message,
    page: context.page || 'assistant',
    context,
  };
}
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && node --test tests/assistant.test.js`

Expected: PASS.

- [ ] **Step 5: Build the assistant page**

Mirror the reference app’s feeling with:
- a left history rail
- a center conversation stream
- a right context/actions rail
- suggestion chips and quick prompts
- card rendering for `shops`, `vouchers`, and generic `cards`
- a fallback local demo mode when no backend answer is available

### Task 6: Polish, verify, and hook the frontend into the existing startup flow

**Files:**
- Modify: `start_all.sh`
- Modify: `frontend/vite.config.js`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.vue` and page components as needed

- [ ] **Step 1: Verify the app builds**

Run: `cd frontend && npm run build`

Expected: success with no TypeScript or bundler errors.

- [ ] **Step 2: Verify tests pass**

Run: `cd frontend && npm test`

Expected: all utility tests pass.

- [ ] **Step 3: Smoke-test the UI**

Run the backend, start the frontend on port `3001`, then click through:
- 首页
- 商铺列表和详情
- 博客列表和详情
- 个人中心
- AI 助手

- [ ] **Step 4: Commit**

```bash
git add frontend start_all.sh docs/superpowers/plans/2026-05-14-vue-user-frontend.md
git commit -m "feat: add vue user frontend"
```
