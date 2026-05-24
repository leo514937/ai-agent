import { createRouter, createWebHashHistory } from 'vue-router';
import { resolveRouteTitle } from '@/lib/navigation.js';
import HomePage from '@/pages/HomePage.vue';
import ShopPage from '@/pages/ShopPage.vue';
import ShopDetailPage from '@/pages/ShopDetailPage.vue';
import BlogPage from '@/pages/BlogPage.vue';
import BlogDetailPage from '@/pages/BlogDetailPage.vue';
import MePage from '@/pages/MePage.vue';
import AiPage from '@/pages/AiPage.vue';
import NotFoundPage from '@/pages/NotFoundPage.vue';

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomePage, meta: { title: '首页', subtitle: '本地生活助手服务台' } },
    { path: '/shops', name: 'shops', component: ShopPage, meta: { title: '商铺', subtitle: '分类、推荐和优惠券' } },
    { path: '/shops/:id', name: 'shop-detail', component: ShopDetailPage, meta: { title: '商铺详情', subtitle: '店铺信息与优惠券' } },
    { path: '/blogs', name: 'blogs', component: BlogPage, meta: { title: '博客', subtitle: '热帖和关注流' } },
    { path: '/blogs/:id', name: 'blog-detail', component: BlogDetailPage, meta: { title: '博客详情', subtitle: '阅读、点赞与笔记' } },
    { path: '/ai', name: 'ai', component: AiPage, meta: { title: 'AI 助手', subtitle: '推荐、对比与解释' } },
    { path: '/me', name: 'me', component: MePage, meta: { title: '个人中心', subtitle: '服务记录和签到' } },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundPage, meta: { title: '未找到', subtitle: '页面不存在' } },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

router.afterEach((to) => {
  const title = to.meta?.title || resolveRouteTitle(to.path);
  document.title = `${title} · 本地生活助手`;
});

export default router;
