<template>
  <div class="page home-page fade-in">
    <section class="page__hero">
      <article class="hero-card panel-strong home-page__hero-main">
        <p class="eyebrow">LOCAL SERVICE WORKBENCH</p>
        <h2 class="hero-title">直接进入服务页面</h2>
        <p class="hero-copy">
          基于本地生活助手后端的服务台，启动后不展示登录页，直接进入店铺、博客、个人中心和 AI 助手。
          如果后端暂时不可用，也会自动切回本地演示数据。
        </p>

        <div class="hero-actions">
          <RouterLink class="btn btn-primary" to="/shops">立即看店</RouterLink>
          <RouterLink class="btn btn-secondary" to="/blogs">浏览博客</RouterLink>
          <RouterLink class="btn btn-secondary" to="/ai">打开 AI 助手</RouterLink>
        </div>
      </article>

      <div class="hero-side">
        <div class="grid-2">
          <StatCard label="服务入口" :value="5" hint="首页、商铺、博客、AI、个人中心" />
          <StatCard label="推荐店铺" :value="featuredShops.length" hint="本地演示与后端数据自动兜底" />
        </div>

        <div class="home-page__pulse card panel">
          <p class="home-page__pulse-eyebrow">Service Pulse</p>
          <h3 class="home-page__pulse-title">本地生活助手 + 青蓝高亮的工作台风格</h3>
          <p class="home-page__pulse-copy">
            参考仓库的视觉节奏已经应用到这套前端里，AI 页面也会沿用同一套布局和配色。
          </p>
          <div class="home-page__pulse-actions">
            <RouterLink class="chip chip--active" :to="{ path: '/shops', query: { type: 1 } }">先看火锅</RouterLink>
            <RouterLink class="chip chip--active" to="/blogs">先看热帖</RouterLink>
          </div>
        </div>
      </div>
    </section>

    <section class="section">
      <SectionTitle
        eyebrow="Catalog"
        title="分类入口"
        subtitle="从这里进入商铺分类浏览，每个入口都直接可点。"
      />

      <div v-if="loading" class="panel home-page__loading">
        正在加载服务目录...
      </div>

      <div v-else class="grid-fluid">
        <RouterLink
          v-for="type in types"
          :key="type.id"
          class="home-page__type card card--hover"
          :to="{ path: '/shops', query: { type: type.id } }"
        >
          <span class="home-page__type-icon">{{ (type.icon && type.icon.includes('/')) ? type.name.charAt(0) : (type.icon || type.name.charAt(0)) }}</span>
          <div>
            <h3 class="home-page__type-title">{{ type.name }}</h3>
            <p class="home-page__type-copy">{{ type.summary }}</p>
          </div>
        </RouterLink>
      </div>
    </section>

    <section class="section">
      <SectionTitle
        eyebrow="Featured"
        title="推荐商铺"
        subtitle="来自后端或本地演示的精选店铺，适合直接进入详情。"
      >
        <template #actions>
          <RouterLink class="chip chip--active" to="/shops">查看全部</RouterLink>
        </template>
      </SectionTitle>

      <div class="grid-fluid">
        <ShopCard v-for="shop in featuredShops" :key="shop.id" :shop="shop" />
      </div>
    </section>

    <section class="section">
      <SectionTitle
        eyebrow="Blog"
        title="热度笔记"
        subtitle="浏览商圈探店内容，或者把博客丢给 AI 继续分析。"
      >
        <template #actions>
          <RouterLink class="chip chip--active" to="/blogs">进入博客流</RouterLink>
        </template>
      </SectionTitle>

      <div class="grid-fluid">
        <BlogCard v-for="blog in blogs" :key="blog.id" :blog="blog" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import BlogCard from '@/components/BlogCard.vue';
import SectionTitle from '@/components/SectionTitle.vue';
import ShopCard from '@/components/ShopCard.vue';
import StatCard from '@/components/StatCard.vue';
import { loadHomeSnapshot } from '@/lib/catalog.js';

const loading = ref(true);
const types = ref([]);
const featuredShops = ref([]);
const blogs = ref([]);

async function loadPage() {
  loading.value = true;
  try {
    const snapshot = await loadHomeSnapshot();
    types.value = Array.isArray(snapshot.types) ? snapshot.types : [];
    featuredShops.value = Array.isArray(snapshot.featuredShops) ? snapshot.featuredShops : [];
    blogs.value = Array.isArray(snapshot.blogs) ? snapshot.blogs : [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadPage);
</script>

<style scoped>
.home-page__hero-main {
  min-height: 100%;
}

.home-page__pulse {
  display: grid;
  gap: 12px;
  padding: 18px;
  border-radius: 28px;
}

.home-page__pulse-eyebrow {
  margin: 0;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.home-page__pulse-title {
  margin: 0;
  font-size: 1.02rem;
  font-weight: 900;
}

.home-page__pulse-copy {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.7;
}

.home-page__pulse-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.home-page__loading {
  padding: 18px;
  border-radius: 22px;
  color: var(--text-soft);
}

.home-page__type {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-radius: 22px;
}

.home-page__type-icon {
  flex: none;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  color: white;
  font-size: 1.1rem;
  font-weight: 900;
  background: linear-gradient(145deg, rgba(8, 145, 178, 0.96), rgba(16, 185, 129, 0.76));
  box-shadow: 0 12px 28px rgba(8, 145, 178, 0.18);
}

.home-page__type-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 900;
}

.home-page__type-copy {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.6;
  font-size: 0.86rem;
}

@media (max-width: 720px) {
  .home-page__type {
    align-items: start;
  }
}
</style>
