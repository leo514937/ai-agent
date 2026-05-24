<template>
  <header class="app-header panel">
    <div class="brand">
      <div class="brand__mark">点</div>
      <div class="brand__text">
        <h1 class="brand__title">本地生活助手</h1>
        <p class="brand__subtitle">{{ subtitle }}</p>
      </div>
    </div>

    <form class="header-search" @submit.prevent="$emit('search', searchText)">
      <input
        v-model="searchText"
        class="search-input"
        type="search"
        placeholder="搜索附近商铺、店名或热门关键词"
        aria-label="搜索商铺"
      />
      <button class="btn btn-primary" type="submit">搜索</button>
    </form>

    <div class="header-actions">
      <button class="btn btn-secondary" type="button" @click="$emit('toggle-theme')">
        {{ theme === 'dark' ? '浅色' : '深色' }}
      </button>
    </div>
  </header>
</template>

<script setup>
import { ref, watch } from 'vue';

defineProps({
  subtitle: {
    type: String,
    default: '',
  },
  theme: {
    type: String,
    default: 'dark',
  },
  backendStatus: {
    type: Object,
    default: () => ({ kind: 'offline', label: '本地演示' }),
  },
});

defineEmits(['toggle-theme', 'search']);

const searchText = ref('');

watch(
  () => searchText.value,
  (value) => {
    if (typeof window === 'undefined') {
      return;
    }
    if (value === '') {
      return;
    }
  },
);
</script>
