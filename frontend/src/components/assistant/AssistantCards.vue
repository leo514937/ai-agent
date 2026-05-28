<template>
  <div class="assistant-message__extensions">
    <!-- 整合后的推荐店铺 & 优惠券重叠气泡组 -->
    <div
      v-if="assistantShops.length || assistantVouchers.length"
      class="assistant-message__bubbles-stack-container"
      title="点击查看推荐资源详情"
      @click="openAllDetails"
    >
      <div class="assistant-message__bubbles-stack">
        <!-- 渲染店铺头像组 (最多显示前3个) -->
        <div
          v-for="(shop, index) in assistantShops.slice(0, 3)"
          :key="'stack-shop-' + cardKey(shop)"
          class="stack-circle stack-circle--shop"
          :style="{ zIndex: 10 + index, marginLeft: index === 0 ? '0px' : '-16px' }"
        >
          {{ shop.name ? shop.name.charAt(0) : (shop.typeIcon || '店') }}
        </div>
        
        <!-- 渲染优惠券头像组 (最多显示前3个) -->
        <div
          v-for="(voucher, index) in assistantVouchers.slice(0, 3)"
          :key="'stack-voucher-' + cardKey(voucher)"
          class="stack-circle stack-circle--voucher"
          :style="{ zIndex: 20 + index, marginLeft: '-16px' }"
        >
          {{ getVoucherBubbleText(voucher) }}
        </div>
        
        <!-- 省略号/折叠计数圆圈 -->
        <div
          v-if="assistantShops.length > 3 || assistantVouchers.length > 3"
          class="stack-circle stack-circle--more"
          :style="{ zIndex: 30, marginLeft: '-16px' }"
        >
          ...
        </div>
      </div>
    </div>

    <!-- 更多卡片 (RenderableCards - 已过滤店铺与优惠券大卡片) -->
    <div v-if="renderableCards.length" class="assistant-message__section">
      <div class="assistant-message__section-title">更多卡片</div>
      <div class="assistant-message__cards">
        <article v-for="card in renderableCards" :key="card.key" class="assistant-message__generic-card">
          <div class="assistant-message__generic-card-head">
            <strong>{{ cardTitle(card.value) }}</strong>
            <span v-if="cardBadge(card.value)" class="assistant-message__generic-card-badge">{{ cardBadge(card.value) }}</span>
          </div>
          <p v-if="cardDescription(card.value)" class="assistant-message__generic-card-copy">
            {{ cardDescription(card.value) }}
          </p>
        </article>
      </div>
    </div>

    <!-- 整合后的详情大弹窗 -->
    <Teleport to="body">
      <Transition name="modal-fade">
        <div v-if="showAllModal" class="shop-modal-overlay" @click.self="closeAllModal">
          <div class="shop-modal-container shop-modal-container--wide" @click.stop>
            <div class="shop-modal-header">
              <h3>{{ modalTitle }}</h3>
              <button class="shop-modal-close" @click="closeAllModal">×</button>
            </div>
            <div class="shop-modal-body shop-modal-body--combined">
              <!-- 店铺列表 -->
              <div v-if="assistantShops.length" class="modal-section">
                <div class="modal-section-title">推荐店铺</div>
                <div class="modal-section-grid">
                  <ShopCard v-for="shop in assistantShops" :key="cardKey(shop)" :shop="shop" />
                </div>
              </div>
              
              <!-- 优惠券列表 -->
              <div v-if="assistantVouchers.length" class="modal-section">
                <div class="modal-section-title">优惠券</div>
                <div class="modal-section-grid">
                  <VoucherCard v-for="voucher in assistantVouchers" :key="cardKey(voucher)" :voucher="voucher" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
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

const modalTitle = computed(() => {
  const shopCount = assistantShops.value.length;
  const voucherCount = assistantVouchers.value.length;
  
  if (shopCount && voucherCount) {
    return `为您推荐了 ${shopCount} 家店铺 和 ${voucherCount} 张优惠券`;
  } else if (shopCount) {
    return `为您推荐了 ${shopCount} 家店铺`;
  } else if (voucherCount) {
    return `为您推荐了 ${voucherCount} 张优惠券`;
  }
  return '推荐资源详情';
});

// 重叠气泡组 Modal 控制逻辑
const showAllModal = ref(false);

function openAllDetails() {
  showAllModal.value = true;
}

function closeAllModal() {
  showAllModal.value = false;
}

const getVoucherBubbleText = (voucher) => {
  if (!voucher) return '券';
  const price = voucher.price || voucher.priceValue || voucher.value;
  if (price !== undefined && price !== null) {
    const numeric = parseFloat(price);
    if (!isNaN(numeric)) {
      return `￥${Math.round(numeric)}`;
    }
  }
  return voucher.title ? voucher.title.charAt(0) : '券';
};

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
  if (!Array.isArray(props.message.cards)) return [];
  return props.message.cards
    .map((item, index) => ({
      key: cardKey(item, index),
      kind: cardKind(item),
      value: item,
    }))
    .filter(card => card.kind !== 'shop' && card.kind !== 'voucher');
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

/* 重叠气泡组容器 */
.assistant-message__bubbles-stack-container {
  display: inline-flex;
  align-items: center;
  background: linear-gradient(135deg, rgba(30, 41, 59, 0.45), rgba(15, 23, 42, 0.45));
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0.375rem 0.75rem 0.375rem 0.375rem;
  border-radius: 9999px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  margin-top: 0.75rem;
}

.assistant-message__bubbles-stack-container:hover {
  background: linear-gradient(135deg, rgba(8, 145, 178, 0.12), rgba(16, 185, 129, 0.08));
  border-color: rgba(8, 145, 178, 0.3);
  box-shadow: 0 4px 20px rgba(8, 145, 178, 0.15);
  transform: translateY(-1px);
}

/* 气泡叠层 (Avatar Group) */
.assistant-message__bubbles-stack {
  display: flex;
  align-items: center;
}

.stack-circle {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 850;
  backdrop-filter: blur(8px);
  border: 2px solid var(--surface, #1e293b); /* 用边框制造重叠层次感！ */
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
}

.assistant-message__bubbles-stack-container:hover .stack-circle {
  transform: scale(1.04);
  border-color: rgba(8, 145, 178, 0.2);
}

/* 店铺专属渐变 */
.stack-circle--shop {
  background: linear-gradient(135deg, rgba(8, 145, 178, 0.9), rgba(16, 185, 129, 0.9));
}

/* 优惠券专属渐变 */
.stack-circle--voucher {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.9), rgba(245, 158, 11, 0.9));
  font-size: 0.82rem;
}

/* 省略号/更多圆圈 */
.stack-circle--more {
  background: linear-gradient(135deg, rgba(51, 65, 85, 0.9), rgba(30, 41, 59, 0.9));
  color: var(--text-soft);
  font-weight: 900;
  font-size: 1.1rem;
}

/* 提示文案与动作 */
.bubbles-stack-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bubbles-stack-text {
  font-size: 0.78rem;
  color: var(--text-soft, #94a3b8);
  font-weight: 600;
  line-height: 1.2;
}

.highlight--shop {
  color: rgba(34, 211, 238, 1); /* 高亮青色 */
}

.highlight--voucher {
  color: rgba(251, 146, 60, 1); /* 高亮橙黄色 */
}

.bubbles-stack-action-hint {
  font-size: 0.68rem;
  color: var(--primary, #0891b2);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s ease;
}

.assistant-message__bubbles-stack-container:hover .bubbles-stack-action-hint {
  color: var(--primary-strong, #06b6d4);
}

.arrow-icon {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.assistant-message__bubbles-stack-container:hover .arrow-icon {
  transform: translateX(3px);
}

/* 宽屏弹窗 */
.shop-modal-container--wide {
  max-width: 580px; /* 适当放宽以容纳双列或大卡片 */
}

.shop-modal-body--combined {
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
  padding: 1.5rem;
}

.modal-section-title {
  font-size: 0.92rem;
  font-weight: 800;
  color: var(--text-soft, #94a3b8);
  margin-bottom: 0.875rem;
  padding-left: 6px;
  border-left: 3px solid var(--primary, #0891b2);
}

.modal-section-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Modal 遮罩和弹窗 */
.shop-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(8px);
  display: grid;
  place-items: center;
  z-index: 9999;
}

.shop-modal-container {
  background: var(--surface, #1e293b);
  border: 1px solid var(--line, #334155);
  border-radius: 1.25rem;
  width: 90%;
  max-width: 480px;
  max-height: 85vh;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 10px 10px -5px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: modal-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes modal-pop {
  from {
    transform: scale(0.9) translateY(10px);
    opacity: 0;
  }
  to {
    transform: scale(1) translateY(0);
    opacity: 1;
  }
}

.shop-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--line, #334155);
}

.shop-modal-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
  color: var(--text, #f1f5f9);
}

.shop-modal-close {
  background: none;
  border: none;
  color: var(--muted, #64748b);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0 0.25rem;
  line-height: 1;
  transition: color 0.2s ease;
}

.shop-modal-close:hover {
  color: var(--text, #f1f5f9);
}

.shop-modal-body {
  padding: 1.25rem;
  overflow-y: auto;
  flex: 1;
}

.shop-modal-body--list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Transition 动效 */
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.25s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
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
