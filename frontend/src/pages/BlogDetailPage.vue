<template>
  <div class="page blog-detail-page fade-in">
    <section class="page__hero">
      <article class="hero-card panel-strong blog-detail-page__hero">
        <div class="blog-detail-page__media">
          <img v-if="blog.cover" :src="blog.cover" :alt="blog.title" />
          <div class="blog-detail-page__media-overlay">
            <span class="tag tag--accent">{{ blog.authorLabel || blog.name || '本地生活助手' }}</span>
            <span class="tag">{{ blog.likeText || blog.liked || 0 }} 赞</span>
          </div>
        </div>

        <div class="blog-detail-page__hero-body">
          <p class="eyebrow">BLOG DETAIL</p>
          <h2 class="hero-title">{{ blog.title || '正在加载...' }}</h2>
          <p class="hero-copy">{{ blog.summary || blog.content || '博客详情正在准备中。' }}</p>

          <div class="hero-actions">
            <span class="chip">{{ blog.metaText || '本地生活笔记' }}</span>
            <span class="chip">评论 {{ blog.commentText || blog.comments || 0 }}</span>
            <span class="chip">喜欢 {{ blog.likeText || blog.liked || 0 }}</span>
          </div>

          <div class="hero-actions">
            <button class="btn btn-primary" type="button" @click="openAi">让 AI 继续分析</button>
            <RouterLink class="btn btn-secondary" to="/blogs">返回博客列表</RouterLink>
          </div>
        </div>
      </article>

      <div class="hero-side">
        <StatCard label="点赞" :value="blog.likeText || blog.liked || 0" hint="帖子热度与用户互动" />
        <StatCard label="评论" :value="blog.commentText || blog.comments || 0" hint="讨论和口碑反馈" />
      </div>
    </section>

    <section class="blog-detail-page__layout">
      <article class="card panel blog-detail-page__article">
        <SectionTitle eyebrow="Article" title="正文内容" subtitle="阅读文章原文，并观察店铺和观点如何被拆解。">
          <template #actions>
            <span class="chip">{{ blog.shopId ? `关联店铺 #${blog.shopId}` : '独立博客' }}</span>
          </template>
        </SectionTitle>

        <p class="blog-detail-page__content">{{ blog.content || blog.summary || '暂无正文内容。' }}</p>

        <div v-if="blog.tags?.length" class="blog-detail-page__tags">
          <span v-for="tag in blog.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
      </article>

      <aside class="blog-detail-page__rail">
        <article class="card panel blog-detail-page__author">
          <div class="blog-detail-page__author-top">
            <div class="avatar avatar--lg">{{ blog.icon || '笔' }}</div>
            <div>
              <p class="blog-detail-page__rail-title">作者</p>
              <h3 class="blog-detail-page__rail-name">{{ blog.authorLabel || blog.name || '本地生活助手' }}</h3>
            </div>
          </div>
          <p class="blog-detail-page__rail-copy">
            {{ blog.metaText || '这里会展示作者信息、热度和关联店铺。' }}
          </p>
        </article>

        <article class="card panel blog-detail-page__author">
          <SectionTitle eyebrow="Likes" title="点赞用户" subtitle="喜欢这篇文章的人。">
            <template #actions>
              <span class="chip">{{ likes.length }} 人</span>
            </template>
          </SectionTitle>

          <div class="blog-detail-page__likes">
            <div v-for="user in likes" :key="user.id" class="blog-detail-page__like">
              <span class="avatar">{{ user.icon || user.nickName?.slice(0, 1) || 'U' }}</span>
              <div>
                <strong>{{ user.nickName }}</strong>
                <span>点赞用户</span>
              </div>
            </div>
          </div>
        </article>

        <article v-if="relatedShop" class="card panel blog-detail-page__author">
          <SectionTitle eyebrow="Related Shop" title="关联店铺" subtitle="这篇文章最相关的店铺。">
            <template #actions>
              <RouterLink class="chip chip--active" :to="`/shops/${relatedShop.id}`">去看看</RouterLink>
            </template>
          </SectionTitle>
          <ShopCard :shop="relatedShop" />
        </article>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import SectionTitle from '@/components/SectionTitle.vue';
import ShopCard from '@/components/ShopCard.vue';
import StatCard from '@/components/StatCard.vue';
import { loadBlogDetail, loadBlogLikes, loadShopDetail } from '@/lib/catalog.js';

const route = useRoute();
const router = useRouter();

const blog = ref({});
const likes = ref([]);
const relatedShop = ref(null);

async function loadDetail() {
  const id = Number(route.params.id);
  blog.value = await loadBlogDetail(id);
  likes.value = await loadBlogLikes(id);
  relatedShop.value = blog.value.shopId ? await loadShopDetail(blog.value.shopId) : null;
}

function openAi() {
  if (!blog.value?.id) {
    return;
  }

  router.push({
    path: '/ai',
    query: {
      page: 'blogs',
      blogId: String(blog.value.id),
      blogTitle: blog.value.title,
      shopName: relatedShop.value?.name,
      typeName: relatedShop.value?.typeName,
    },
  });
}

watch(
  () => route.params.id,
  loadDetail,
  { immediate: true },
);
</script>

<style scoped>
.blog-detail-page__hero {
  display: grid;
  gap: 18px;
  padding: 0;
  overflow: hidden;
}

.blog-detail-page__media {
  position: relative;
  aspect-ratio: 16 / 8;
  background:
    linear-gradient(135deg, rgba(8, 145, 178, 0.2), rgba(16, 185, 129, 0.16)),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.72));
}

.blog-detail-page__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.blog-detail-page__media-overlay {
  position: absolute;
  inset: auto 0 0;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 16px;
  background: linear-gradient(180deg, transparent, rgba(2, 6, 23, 0.58));
  color: #fff;
}

.blog-detail-page__hero-body {
  display: grid;
  gap: 14px;
  padding: 0 24px 24px;
}

.blog-detail-page__layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.85fr);
  gap: 18px;
}

.blog-detail-page__article,
.blog-detail-page__author {
  padding: 18px;
  border-radius: 22px;
  display: grid;
  gap: 14px;
}

.blog-detail-page__content {
  margin: 0;
  color: var(--text);
  line-height: 1.9;
  font-size: 1rem;
  white-space: pre-wrap;
}

.blog-detail-page__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.blog-detail-page__rail {
  display: grid;
  gap: 18px;
  align-self: start;
}

.blog-detail-page__author-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.blog-detail-page__rail-title {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.blog-detail-page__rail-name {
  margin: 0;
  font-size: 1rem;
  font-weight: 900;
}

.blog-detail-page__rail-copy {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.75;
}

.blog-detail-page__likes {
  display: grid;
  gap: 10px;
}

.blog-detail-page__like {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 18px;
  background: var(--surface-muted);
  border: 1px solid var(--line);
}

.blog-detail-page__like strong,
.blog-detail-page__like span {
  display: block;
}

.blog-detail-page__like strong {
  font-size: 0.92rem;
  font-weight: 850;
}

.blog-detail-page__like span {
  color: var(--muted);
  font-size: 0.78rem;
  margin-top: 4px;
}

@media (max-width: 920px) {
  .blog-detail-page__layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .blog-detail-page__hero-body {
    padding: 0 16px 18px;
  }
}
</style>
