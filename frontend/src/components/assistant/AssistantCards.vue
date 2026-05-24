<template>
  <div class="assistant-message__extensions">
    <div v-if="assistantShops.length" class="assistant-message__section">
      <div class="assistant-message__section-title">推荐店铺</div>
      <div class="assistant-message__cards">
        <ShopCard v-for="shop in assistantShops" :key="cardKey(shop)" :shop="shop" />
      </div>
    </div>
    
    <div v-if="assistantVouchers.length" class="assistant-message__section">
      <div class="assistant-message__section-title">优惠券</div>
      <div class="assistant-message__cards">
        <VoucherCard v-for="voucher in assistantVouchers" :key="cardKey(voucher)" :voucher="voucher" />
      </div>
    </div>
    
    <div v-if="renderableCards.length" class="assistant-message__section">
      <div class="assistant-message__section-title">更多卡片</div>
      <div class="assistant-message__cards">
        <template v-for="card in renderableCards" :key="card.key">
          <ShopCard v-if="card.kind === 'shop'" :shop="card.value" />
          <VoucherCard v-else-if="card.kind === 'voucher'" :voucher="card.value" />
          <article v-else class="assistant-message__generic-card">
            <div class="assistant-message__generic-card-head">
              <strong>{{ cardTitle(card.value) }}</strong>
              <span v-if="cardBadge(card.value)" class="assistant-message__generic-card-badge">{{ cardBadge(card.value) }}</span>
            </div>
            <p v-if="cardDescription(card.value)" class="assistant-message__generic-card-copy">
              {{ cardDescription(card.value) }}
            </p>
          </article>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import ShopCard from '@/components/ShopCard.vue';
import VoucherCard from '@/components/VoucherCard.vue';

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
});

const assistantShops = computed(() => (Array.isArray(props.message.shops) ? props.message.shops : []));
const assistantVouchers = computed(() => (Array.isArray(props.message.vouchers) ? props.message.vouchers : []));

function cardKey(item, index = 0) {
  if (!item || typeof item !== 'object') {
    return `card-${index}-${String(item || '')}`;
  }
  return String(item.id || item.key || item.name || item.title || index);
}

function cardKind(item) {
  if (!item || typeof item !== 'object') return 'unknown';
  if (item.shopId || item.shopName || item.shop_id || item.shop_name) return 'shop';
  if (item.voucherId || item.voucher_id || item.price) return 'voucher';
  if (item.kind || item.type) return item.kind || item.type;
  return 'generic';
}

function cardTitle(item) {
  if (!item || typeof item !== 'object') return String(item || '');
  return String(item.title || item.name || item.label || '参考卡片');
}

function cardDescription(item) {
  if (!item || typeof item !== 'object') return '';
  return String(item.description || item.desc || item.summary || item.text || '');
}

function cardBadge(item) {
  if (!item || typeof item !== 'object') return '';
  return String(item.badge || item.tag || item.status || '');
}

const renderableCards = computed(() => {
  return Array.isArray(props.message.cards)
    ? props.message.cards.map((item, index) => ({
        key: cardKey(item, index),
        kind: cardKind(item),
        value: item,
      }))
    : [];
});
</script>

<style scoped>
.assistant-message__section {
  margin-top: 1.5rem;
}
.assistant-message__section-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-soft);
  margin-bottom: 0.75rem;
}
.assistant-message__cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.assistant-message__generic-card {
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  padding: 1rem;
  background-color: var(--surface);
}
.assistant-message__generic-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.assistant-message__generic-card-badge {
  background-color: var(--surface-muted);
  color: var(--text-soft);
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.75rem;
}
.assistant-message__generic-card-copy {
  margin: 0;
  font-size: 0.875rem;
  color: var(--muted);
}
</style>
