<template>
  <div class="page shop-page fade-in">
    <section class="page__hero">
      <article class="hero-card panel-strong">
        <p class="eyebrow">SHOP EXPLORER</p>
        <h2 class="hero-title">商铺列表</h2>
        <p class="hero-copy">
          用分类和关键词快速浏览店铺。你在顶部搜索框输入的内容会直接跳到这里。
        </p>

        <div class="hero-actions">
          <span class="chip">当前分类：{{ currentTypeName }}</span>
          <span class="chip">关键词：{{ keyword || '全部' }}</span>
          <span class="chip">结果数：{{ shops.length }}</span>
        </div>
      </article>

      <div class="hero-side">
        <StatCard label="分类" :value="types.length" hint="点击切换火锅、咖啡、甜品等分类" />
        <StatCard label="结果" :value="shops.length" hint="后端优先，失败后自动回到本地演示" />
      </div>
    </section>

    <section class="section">
      <SectionTitle
        eyebrow="Filters"
        title="分类筛选"
        subtitle="直接按店铺类型切换，也可以叠加关键词搜索。"
      />

      <div class="shop-page__filters">
        <button
          :class="['chip', selectedTypeId === 'all' && 'chip--active']"
          type="button"
          @click="setType('all')"
        >
          全部
        </button>
        <button
          v-for="type in types"
          :key="type.id"
          :class="['chip', selectedTypeId === String(type.id) && 'chip--active']"
          type="button"
          @click="setType(type.id)"
        >
          {{ type.icon }} {{ type.name }}
        </button>
        <button v-if="hasQuery" class="chip chip--active" type="button" @click="clearQuery">
          清除关键词
        </button>
      </div>
    </section>

    <section class="section">
      <SectionTitle
        eyebrow="Results"
        title="商铺列表"
        subtitle="列表页展示的是可直接进入的详情卡片。"
      />

      <div v-if="loading" class="panel shop-page__loading">
        正在加载商铺列表...
      </div>

      <div v-else-if="shops.length" class="grid-fluid">
        <ShopCard v-for="shop in shops" :key="shop.id" :shop="shop" />
      </div>

      <EmptyState
        v-else
        glyph="店"
        title="没有找到符合条件的商铺"
        description="试着切换分类，或者清除关键词后再看。"
        action-label="重置筛选"
        @action="resetFilters"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EmptyState from '@/components/EmptyState.vue';
import SectionTitle from '@/components/SectionTitle.vue';
import ShopCard from '@/components/ShopCard.vue';
import StatCard from '@/components/StatCard.vue';
import { loadShopTypes, loadShopsPage } from '@/lib/catalog.js';

const route = useRoute();
const router = useRouter();

const loading = ref(true);
const types = ref([]);
const shops = ref([]);

const selectedTypeId = computed(() => String(route.query.type || 'all'));
const keyword = computed(() => String(route.query.q || '').trim());
const hasQuery = computed(() => keyword.value.length > 0 || selectedTypeId.value !== 'all');
const currentTypeName = computed(() => {
  if (selectedTypeId.value === 'all') {
    return '全部';
  }
  return types.value.find((item) => String(item.id) === selectedTypeId.value)?.name || '分类';
});

async function loadTypes() {
  types.value = await loadShopTypes();
}

async function loadList() {
  loading.value = true;
  try {
    shops.value = await loadShopsPage({
      typeId: selectedTypeId.value,
      query: keyword.value,
    });
  } finally {
    loading.value = false;
  }
}

function setType(typeId) {
  router.push({
    path: '/shops',
    query: {
      ...(keyword.value ? { q: keyword.value } : {}),
      ...(String(typeId) === 'all' ? {} : { type: String(typeId) }),
    },
  });
}

function clearQuery() {
  router.push({
    path: '/shops',
    query: selectedTypeId.value === 'all' ? {} : { type: selectedTypeId.value },
  });
}

function resetFilters() {
  router.push({ path: '/shops' });
}

onMounted(loadTypes);

watch(
  () => [route.query.type, route.query.q],
  loadList,
  { immediate: true },
);
</script>

<style scoped>
.shop-page__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shop-page__loading {
  padding: 18px;
  border-radius: 22px;
  color: var(--text-soft);
}
</style>
