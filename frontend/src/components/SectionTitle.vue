<template>
  <div class="section__head">
    <div>
      <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
      <h2 class="section__title">{{ title }}</h2>
      <p v-if="subtitle" class="section__subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="section__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  eyebrow: {
    type: String,
    default: '',
  },
  title: {
    type: String,
    required: true,
  },
  subtitle: {
    type: String,
    default: '',
  },
});
</script>
