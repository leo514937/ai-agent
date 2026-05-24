<template>
  <article class="profile-card card panel-strong">
    <div class="profile-card__header">
      <div class="avatar avatar--xl">{{ profile.icon || '我' }}</div>
      <div class="profile-card__info">
        <p class="profile-card__eyebrow">{{ profile.level || '游客模式' }}</p>
        <h3 class="profile-card__name">{{ profile.nickName || '黑马游客' }}</h3>
        <p class="profile-card__copy">
          <span v-if="profile.city">{{ profile.city }} · </span>
          {{ profile.bio || '现在直接进入服务页面浏览店铺、博客和 AI 助手。' }}
        </p>
      </div>
    </div>

    <div class="profile-card__actions">
      <span class="chip">{{ signedLabel }}</span>
      <button v-if="actionLabel" class="btn btn-primary" type="button" @click="$emit('action')">
        {{ actionLabel }}
      </button>
    </div>

    <div v-if="stats.length" class="profile-card__stats">
      <article v-for="item in stats" :key="item.label" class="profile-stat">
        <p class="profile-stat__label">{{ item.label }}</p>
        <strong class="profile-stat__value">{{ item.value }}</strong>
        <span v-if="item.hint" class="profile-stat__hint">{{ item.hint }}</span>
      </article>
    </div>
  </article>
</template>

<script setup>
defineProps({
  profile: {
    type: Object,
    required: true,
  },
  stats: {
    type: Array,
    default: () => [],
  },
  actionLabel: {
    type: String,
    default: '今日签到',
  },
  signedLabel: {
    type: String,
    default: '游客态',
  },
});

defineEmits(['action']);
</script>

<style scoped>
.profile-card {
  display: grid;
  gap: 16px;
  padding: 18px;
  border-radius: 24px;
}

.profile-card__header {
  display: flex;
  align-items: start;
  gap: 14px;
}

.profile-card__info {
  min-width: 0;
}

.profile-card__eyebrow {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.profile-card__name {
  margin: 0;
  font-size: 1.08rem;
  font-weight: 900;
}

.profile-card__copy {
  margin: 10px 0 0;
  color: var(--text-soft);
  line-height: 1.7;
}

.profile-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.profile-card__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.profile-stat {
  padding: 14px;
  border-radius: 18px;
  background: var(--surface-muted);
  border: 1px solid var(--line);
}

.profile-stat__label {
  margin: 0;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  text-transform: uppercase;
  letter-spacing: 0.14em;
}

.profile-stat__value {
  display: block;
  margin-top: 8px;
  font-size: 1.15rem;
  font-weight: 900;
}

.profile-stat__hint {
  display: block;
  margin-top: 6px;
  color: var(--text-soft);
  font-size: 0.8rem;
  line-height: 1.55;
}

@media (max-width: 720px) {
  .profile-card__stats {
    grid-template-columns: 1fr;
  }
}
</style>
