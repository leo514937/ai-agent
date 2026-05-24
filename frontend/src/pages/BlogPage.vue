<template>
  <div class="page blog-page fade-in">
    <section class="page__hero">
      <article class="hero-card panel-strong">
        <p class="eyebrow">BLOG STREAM</p>
        <h2 class="hero-title">博客内容流</h2>
        <p class="hero-copy">
          热门探店、关注流和本地笔记都可以直接阅读。看完博客后，也能直接交给 AI 继续分析。
        </p>

        <div class="hero-actions">
          <span class="chip">热门 {{ hotBlogs.length }}</span>
          <span class="chip">关注流 {{ followBlogs.length }}</span>
          <span class="chip">点赞总数 {{ likeTotal }}</span>
        </div>
      </article>

      <div class="hero-side">
        <StatCard label="文章" :value="visibleBlogs.length" hint="切换热门 / 关注流查看不同视角" />
        <StatCard label="互动" :value="likeTotal" hint="来自博客点赞数的合计统计" />
      </div>
    </section>

    <section class="section">
      <SectionTitle eyebrow="Feeds" title="博客流" subtitle="点击顶部按钮切换热门博客和关注流。" />

      <div class="blog-page__tabs">
        <button
          :class="['chip', activeTab === 'hot' && 'chip--active']"
          type="button"
          @click="activeTab = 'hot'"
        >
          热门博客
        </button>
        <button
          :class="['chip', activeTab === 'follow' && 'chip--active']"
          type="button"
          @click="activeTab = 'follow'"
        >
          关注流
        </button>
      </div>
    </section>

    <section class="section">
      <div v-if="loading" class="panel blog-page__loading">
        正在加载博客内容...
      </div>

      <div v-else-if="visibleBlogs.length" class="grid-fluid">
        <BlogCard v-for="blog in visibleBlogs" :key="blog.id" :blog="blog" />
      </div>

      <EmptyState
        v-else
        glyph="文"
        title="暂时没有博客内容"
        description="后端没有返回数据时，会自动显示本地演示内容。"
        action-label="回到首页"
        @action="goHome"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import BlogCard from '@/components/BlogCard.vue';
import EmptyState from '@/components/EmptyState.vue';
import SectionTitle from '@/components/SectionTitle.vue';
import StatCard from '@/components/StatCard.vue';
import { loadBlogFeed, loadHotBlogs } from '@/lib/catalog.js';

const router = useRouter();
const loading = ref(true);
const activeTab = ref('hot');
const hotBlogs = ref([]);
const followBlogs = ref([]);

const visibleBlogs = computed(() => (activeTab.value === 'hot' ? hotBlogs.value : followBlogs.value));
const likeTotal = computed(() =>
  visibleBlogs.value.reduce((total, item) => total + Number(item.liked || 0), 0),
);

async function loadPage() {
  loading.value = true;
  try {
    const [hot, follow] = await Promise.all([loadHotBlogs(), loadBlogFeed()]);
    hotBlogs.value = Array.isArray(hot) ? hot : [];
    followBlogs.value = Array.isArray(follow) ? follow : [];
  } finally {
    loading.value = false;
  }
}

function goHome() {
  router.push('/');
}

onMounted(loadPage);
</script>

<style scoped>
.blog-page__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.blog-page__loading {
  padding: 18px;
  border-radius: 22px;
  color: var(--text-soft);
}
</style>
