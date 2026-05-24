<template>
  <nav :class="['nav-list', compact && 'nav-list--compact']">
    <RouterLink
      v-for="item in items"
      :key="item.path"
      :to="item.path"
      :class="['nav-item', isActive(item.path) && 'nav-item--active']"
      @click="$emit('navigate')"
    >
      <span :class="['nav-item__icon', `nav-item__icon--${item.tone}`]">{{ item.glyph }}</span>
      <span class="nav-item__text">
        <span class="nav-item__label">{{ item.label }}</span>
        <span class="nav-item__hint">{{ item.hint }}</span>
      </span>
    </RouterLink>
  </nav>
</template>

<script setup>
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

const props = defineProps({
  items: {
    type: Array,
    required: true,
  },
  compact: {
    type: Boolean,
    default: false,
  },
});

defineEmits(['navigate']);

const route = useRoute();
const routePath = computed(() => route.path);

function isActive(path) {
  if (path === '/') {
    return routePath.value === '/';
  }

  return routePath.value === path || routePath.value.startsWith(`${path}/`);
}
</script>
