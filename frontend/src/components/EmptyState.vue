<template>
  <div class="empty-state">
    <div class="avatar avatar--ghost">{{ glyph }}</div>
    <div>
      <h3 class="empty-state__title">{{ title }}</h3>
      <p class="empty-state__copy">{{ description }}</p>
    </div>
    <button v-if="actionLabel" class="btn btn-secondary" type="button" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  glyph: {
    type: String,
    default: '空',
  },
  title: {
    type: String,
    default: '暂无内容',
  },
  description: {
    type: String,
    default: '这里还没有数据。',
  },
  actionLabel: {
    type: String,
    default: '',
  },
});

defineEmits(['action']);
</script>
