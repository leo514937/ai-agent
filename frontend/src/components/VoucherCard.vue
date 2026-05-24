<template>
  <article class="voucher-card card card--hover">
    <div class="voucher-card__header">
      <div class="voucher-card__title-group">
        <p class="voucher-card__shop">{{ voucher.shopName || '店铺券' }}</p>
        <h3 class="voucher-card__title">{{ voucher.title }}</h3>
        <p class="voucher-card__subtitle">{{ voucher.subTitle }}</p>
      </div>

      <div class="voucher-card__pricing">
        <strong>{{ voucher.payText }}</strong>
        <span>代 {{ voucher.actualText }}</span>
      </div>
    </div>

    <div class="voucher-card__meta">
      <span class="tag tag--accent">{{ voucher.stockText }}</span>
      <span class="tag">{{ voucher.timeText }}</span>
    </div>

    <p class="voucher-card__rules">{{ voucher.rules }}</p>

    <div class="voucher-card__actions">
      <span v-if="note" class="voucher-card__note">{{ note }}</span>
      <button v-if="actionLabel" class="btn btn-secondary" type="button" @click="$emit('action')">
        {{ actionLabel }}
      </button>
    </div>
  </article>
</template>

<script setup>
defineProps({
  voucher: {
    type: Object,
    required: true,
  },
  actionLabel: {
    type: String,
    default: '咨询 AI',
  },
  note: {
    type: String,
    default: '',
  },
});

defineEmits(['action']);
</script>

<style scoped>
.voucher-card {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.voucher-card__header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 14px;
}

.voucher-card__title-group {
  min-width: 0;
}

.voucher-card__shop {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 850;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.voucher-card__title {
  margin: 0;
  font-size: 1.04rem;
  font-weight: 900;
}

.voucher-card__subtitle {
  margin: 8px 0 0;
  color: var(--text-soft);
  line-height: 1.6;
}

.voucher-card__pricing {
  flex: none;
  display: grid;
  justify-items: end;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 18px;
  background: var(--primary-soft);
  border: 1px solid rgba(8, 145, 178, 0.18);
  color: var(--primary-strong);
}

.voucher-card__pricing strong {
  font-size: 1.35rem;
  font-weight: 900;
}

.voucher-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.voucher-card__rules {
  margin: 0;
  color: var(--muted);
  font-size: 0.88rem;
  line-height: 1.7;
}

.voucher-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.voucher-card__note {
  color: var(--text-soft);
  font-size: 0.82rem;
}
</style>
