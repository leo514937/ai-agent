<template>
  <RouterLink :to="target" class="shop-card card card--hover">
    <div class="shop-card__media">
      <img v-if="cover" :src="cover" :alt="shop.name" />
      <div v-else class="shop-card__fallback">{{ shop.typeIcon || '店' }}</div>
      <div class="shop-card__badge">{{ shop.typeName || '店铺' }}</div>
    </div>

    <div class="shop-card__body">
      <div class="shop-card__head">
        <div class="shop-card__title-group">
          <h3 class="shop-card__title">{{ shop.name }}</h3>
          <p class="shop-card__meta">{{ shop.metaText || formatShopMeta(shop) }}</p>
        </div>
        <span class="shop-card__score">{{ shop.scoreText || '0.0' }}</span>
      </div>

      <div class="shop-card__chips">
        <span v-for="tag in tags" :key="tag" class="tag">{{ tag }}</span>
      </div>

      <div class="shop-card__footer">
        <div class="shop-card__stats">
          <span>{{ shop.distanceText || '步行可达' }}</span>
          <span>{{ shop.sold ? `月售 ${shop.sold}` : '热度待更新' }}</span>
        </div>
        <span class="shop-card__price">{{ shop.priceText || '待补充' }}</span>
      </div>
    </div>
  </RouterLink>
</template>

<script setup>
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { formatShopMeta, normalizeShopImages } from '@/lib/shops.js';

const props = defineProps({
  shop: {
    type: Object,
    required: true,
  },
  to: {
    type: [String, Object],
    default: '',
  },
});

const target = computed(() => props.to || `/shops/${props.shop.id}`);
const cover = computed(() => props.shop.cover || normalizeShopImages(props.shop.images)[0] || '');
const tags = computed(() => (Array.isArray(props.shop.tags) ? props.shop.tags.slice(0, 3) : []));
</script>

<style scoped>
.shop-card {
  display: grid;
  overflow: hidden;
}

.shop-card__media {
  position: relative;
  aspect-ratio: 16 / 10;
  background:
    linear-gradient(135deg, rgba(8, 145, 178, 0.2), rgba(16, 185, 129, 0.16)),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.72));
}

.shop-card__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.shop-card__fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 2rem;
  font-weight: 900;
  letter-spacing: 0.06em;
}

.shop-card__badge {
  position: absolute;
  left: 14px;
  top: 14px;
  padding: 7px 11px;
  border-radius: 999px;
  color: #fff;
  background: rgba(2, 6, 23, 0.48);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 0.78rem;
  font-weight: 800;
}

.shop-card__body {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.shop-card__head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 10px;
}

.shop-card__title-group {
  min-width: 0;
}

.shop-card__title {
  margin: 0;
  font-size: 1.02rem;
  font-weight: 900;
  line-height: 1.38;
}

.shop-card__meta {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 0.86rem;
  line-height: 1.6;
}

.shop-card__score {
  flex: none;
  padding: 7px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-strong);
  border: 1px solid rgba(8, 145, 178, 0.18);
  font-weight: 850;
}

.shop-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shop-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.shop-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--muted);
  font-size: 0.82rem;
}

.shop-card__price {
  flex: none;
  color: var(--text);
  font-size: 0.92rem;
  font-weight: 850;
}
</style>
