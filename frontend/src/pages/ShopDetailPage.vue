<template>
  <div class="page shop-detail-page fade-in">
    <template v-if="notFound">
      <section class="section">
        <EmptyState
          glyph="店"
          title="店铺不存在"
          description="后端数据库中没有找到这家店，请返回商铺列表重新选择。"
          action-label="返回商铺列表"
          @action="goBack"
        />
      </section>
    </template>

    <template v-else>
    <section class="page__hero">
      <article class="hero-card panel-strong shop-detail-page__hero">
        <div class="shop-detail-page__media">
          <img v-if="shop.cover" :src="shop.cover" :alt="shop.name" />
          <div class="shop-detail-page__media-overlay">
            <span class="tag tag--accent">{{ shop.typeName }}</span>
            <span class="tag">{{ shop.scoreText }}</span>
          </div>
        </div>

        <div class="shop-detail-page__hero-body">
          <p class="eyebrow">SHOP DETAIL</p>
          <h2 class="hero-title">{{ shop.name || '正在加载...' }}</h2>
          <p class="hero-copy">{{ shop.metaText || '店铺详情正在准备中。' }}</p>

          <div class="hero-actions">
            <span class="chip">{{ shop.area || '区域' }}</span>
            <span class="chip">{{ shop.priceText || '人均待补充' }}</span>
            <span class="chip">{{ shop.distanceText || '距离待补充' }}</span>
            <span class="chip">{{ shop.openHours || '营业时间待补充' }}</span>
          </div>

          <div class="hero-actions">
            <button class="btn btn-primary" type="button" @click="openAi">让 AI 帮我分析</button>
            <RouterLink class="btn btn-secondary" to="/shops">返回商铺列表</RouterLink>
          </div>
        </div>
      </article>

      <div class="hero-side">
        <StatCard label="评分" :value="shop.scoreText || '0.0'" hint="按后端数据库展示" />
        <StatCard label="月售" :value="shop.sold || 0" hint="代表店铺热度与人气" />
        <StatCard label="评论" :value="shop.comments || 0" hint="口碑和互动数量" />
      </div>
    </section>

    <section class="section">
      <SectionTitle eyebrow="Info" title="店铺信息" subtitle="地址、时间、标签和推荐理由都放在这里。" />

      <div class="grid-2">
        <article class="card panel shop-detail-page__info-card">
          <h3 class="shop-detail-page__subtitle">基础信息</h3>
          <div class="shop-detail-page__meta">
            <span class="tag">地址：{{ shop.address || '未提供' }}</span>
            <span class="tag">营业时间：{{ shop.openHours || '未提供' }}</span>
            <span class="tag">区域：{{ shop.area || '未提供' }}</span>
          </div>
          <p class="shop-detail-page__copy">
            {{ shop.metaText || '店铺基础信息以后端数据库为准。' }}
          </p>
        </article>

        <article class="card panel shop-detail-page__info-card">
          <h3 class="shop-detail-page__subtitle">推荐标签</h3>
          <div class="shop-detail-page__meta">
            <span v-for="tag in shop.tags || []" :key="tag" class="tag tag--accent">{{ tag }}</span>
          </div>
          <p class="shop-detail-page__copy">
            标签用于快速判断这家店适不适合当前场景，比如聚会、办公、约会或夜宵。
          </p>
        </article>
      </div>
    </section>

    <section class="section">
      <SectionTitle eyebrow="Voucher" title="优惠券" subtitle="这里直接展示店铺券和秒杀券，不需要单独登录页。" />

      <div v-if="loading" class="panel shop-detail-page__loading">
        正在加载优惠券...
      </div>

      <div v-else-if="vouchers.length" class="grid-fluid">
        <VoucherCard
          v-for="voucher in vouchers"
          :key="voucher.id"
          :voucher="voucher"
          action-label="咨询 AI"
          note="点击后可以让 AI 解释这张券值不值得领。"
          @action="openAi"
        />
      </div>

      <EmptyState
        v-else
        glyph="券"
        title="暂无优惠券"
        description="这家店暂时没有可展示的券，或后端接口还没返回数据。"
        action-label="返回列表"
        @action="goBack"
      />
    </section>

    <section class="section">
      <SectionTitle eyebrow="Related" title="相关店铺与笔记" subtitle="同类商铺和本店相关博客都在这里。" />

      <div class="grid-2">
        <div class="section">
          <div v-if="relatedShops.length" class="grid-fluid">
            <ShopCard v-for="item in relatedShops" :key="item.id" :shop="item" />
          </div>
          <EmptyState
            v-else
            glyph="店"
            title="没有找到同类店铺"
            description="当前分类下暂时没有更多推荐。"
          />
        </div>

        <div class="section">
          <div v-if="relatedBlogs.length" class="grid-fluid">
            <BlogCard v-for="item in relatedBlogs" :key="item.id" :blog="item" />
          </div>
          <EmptyState
            v-else
            glyph="文"
            title="暂无相关博客"
            description="等后端返回更多内容后，这里会自动补全相关笔记。"
          />
        </div>
      </div>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter, RouterLink } from 'vue-router';
import BlogCard from '@/components/BlogCard.vue';
import EmptyState from '@/components/EmptyState.vue';
import SectionTitle from '@/components/SectionTitle.vue';
import ShopCard from '@/components/ShopCard.vue';
import StatCard from '@/components/StatCard.vue';
import VoucherCard from '@/components/VoucherCard.vue';
import { loadBlogFeed, loadHotBlogs, loadShopDetail, loadShopVouchers, loadShopsPage } from '@/lib/catalog.js';

const route = useRoute();
const router = useRouter();

const loading = ref(true);
const notFound = ref(false);
const shop = ref({});
const vouchers = ref([]);
const relatedShops = ref([]);
const relatedBlogs = ref([]);

const shopId = computed(() => Number(route.params.id));

async function loadDetail() {
  loading.value = true;
  notFound.value = false;
  try {
    const detail = await loadShopDetail(shopId.value);
    if (!detail) {
      shop.value = {};
      vouchers.value = [];
      relatedShops.value = [];
      relatedBlogs.value = [];
      notFound.value = true;
      return;
    }
    shop.value = detail || {};

    const [voucherList, shopList, blogList] = await Promise.all([
      loadShopVouchers(shopId.value),
      loadShopsPage({ typeId: detail?.typeId || 'all', query: '' }),
      loadHotBlogs().catch(() => loadBlogFeed()),
    ]);

    vouchers.value = Array.isArray(voucherList) ? voucherList : [];
    relatedShops.value = (Array.isArray(shopList) ? shopList : []).filter((item) => item.id !== detail?.id).slice(0, 4);
    relatedBlogs.value = (Array.isArray(blogList) ? blogList : []).filter((item) => item.shopId === detail?.id).slice(0, 4);
  } finally {
    loading.value = false;
  }
}

function openAi() {
  if (!shop.value?.id) {
    return;
  }

  router.push({
    path: '/ai',
    query: {
      page: 'shops',
      shopId: String(shop.value.id),
      shopName: shop.value.name,
      typeName: shop.value.typeName,
      area: shop.value.area,
    },
  });
}

function goBack() {
  router.push('/shops');
}

watch(shopId, loadDetail, { immediate: true });
</script>

<style scoped>
.shop-detail-page__hero {
  display: grid;
  gap: 18px;
  padding: 0;
  overflow: hidden;
}

.shop-detail-page__media {
  position: relative;
  aspect-ratio: 16 / 8;
  background:
    linear-gradient(135deg, rgba(8, 145, 178, 0.2), rgba(16, 185, 129, 0.16)),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.72));
}

.shop-detail-page__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.shop-detail-page__media-overlay {
  position: absolute;
  inset: auto 0 0;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 16px;
  background: linear-gradient(180deg, transparent, rgba(2, 6, 23, 0.58));
  color: #fff;
}

.shop-detail-page__hero-body {
  display: grid;
  gap: 14px;
  padding: 0 24px 24px;
}

.shop-detail-page__subtitle {
  margin: 0;
  font-size: 1rem;
  font-weight: 900;
}

.shop-detail-page__info-card {
  display: grid;
  gap: 14px;
  padding: 18px;
  border-radius: 22px;
}

.shop-detail-page__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shop-detail-page__copy {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.75;
}

.shop-detail-page__loading {
  padding: 18px;
  border-radius: 22px;
  color: var(--text-soft);
}

@media (max-width: 720px) {
  .shop-detail-page__hero-body {
    padding: 0 16px 18px;
  }
}
</style>
