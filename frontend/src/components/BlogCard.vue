<template>
  <RouterLink :to="target" class="blog-card card card--hover">
    <div class="blog-card__media">
      <img v-if="cover" :src="cover" :alt="blog.title" />
      <div v-else class="blog-card__fallback">{{ blog.icon || '笔' }}</div>
      <div class="blog-card__overlay">
        <span class="tag tag--accent">{{ blog.isLike ? '已关注' : '热帖' }}</span>
        <span class="blog-card__overlay-stat">赞 {{ blog.likeText || blog.liked || 0 }}</span>
      </div>
    </div>

    <div class="blog-card__body">
      <div class="blog-card__author">
        <div class="avatar">{{ blog.icon || '笔' }}</div>
        <div class="blog-card__author-copy">
          <p class="blog-card__author-name">{{ blog.authorLabel || blog.name || '本地生活助手' }}</p>
          <p class="blog-card__author-meta">{{ blog.metaText || '内容推荐' }}</p>
        </div>
      </div>

      <h3 class="blog-card__title">{{ blog.title }}</h3>
      <p class="blog-card__summary">{{ excerpt }}</p>

      <div class="blog-card__footer">
        <div class="blog-card__chips">
          <span v-for="tag in tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="blog-card__stats">
          <span>赞 {{ blog.likeText || blog.liked || 0 }}</span>
          <span>评 {{ blog.commentText || blog.comments || 0 }}</span>
        </div>
      </div>
    </div>
  </RouterLink>
</template>

<script setup>
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { normalizeShopImages } from '@/lib/shops.js';

const props = defineProps({
  blog: {
    type: Object,
    required: true,
  },
  to: {
    type: [String, Object],
    default: '',
  },
});

const target = computed(() => props.to || `/blogs/${props.blog.id}`);
const cover = computed(() => props.blog.cover || normalizeShopImages(props.blog.images)[0] || '');
const excerpt = computed(() => String(props.blog.summary || props.blog.content || '').slice(0, 90));
const tags = computed(() => (Array.isArray(props.blog.tags) ? props.blog.tags.slice(0, 3) : []));
</script>

<style scoped>
.blog-card {
  display: grid;
  overflow: hidden;
}

.blog-card__media {
  position: relative;
  aspect-ratio: 16 / 10;
  background:
    linear-gradient(135deg, rgba(8, 145, 178, 0.2), rgba(16, 185, 129, 0.16)),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.72));
}

.blog-card__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.blog-card__fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 2rem;
  font-weight: 900;
  letter-spacing: 0.06em;
}

.blog-card__overlay {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px;
  color: #fff;
  background: linear-gradient(180deg, transparent, rgba(2, 6, 23, 0.58));
}

.blog-card__overlay-stat {
  font-size: 0.8rem;
  font-weight: 800;
}

.blog-card__body {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.blog-card__author {
  display: flex;
  align-items: center;
  gap: 12px;
}

.blog-card__author-copy {
  min-width: 0;
}

.blog-card__author-name {
  margin: 0;
  font-size: 0.94rem;
  font-weight: 850;
}

.blog-card__author-meta {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 0.82rem;
}

.blog-card__title {
  margin: 0;
  font-size: 1.02rem;
  font-weight: 900;
  line-height: 1.45;
}

.blog-card__summary {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.7;
  font-size: 0.92rem;
}

.blog-card__footer {
  display: grid;
  gap: 10px;
}

.blog-card__chips,
.blog-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.blog-card__stats {
  color: var(--muted);
  font-size: 0.8rem;
}
</style>
