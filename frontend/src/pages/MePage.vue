<template>
  <div class="page me-page fade-in">
    <section class="page__hero">
      <ProfileCard
        :profile="profile"
        :stats="profileStats"
        :signed-label="signedLabel"
        :action-label="signing ? '签到中' : '今日签到'"
        @action="handleSign"
      />

      <div class="hero-side">
        <StatCard label="签到" :value="signCount" hint="连续签到天数会在这里展示" />
        <StatCard label="收藏" :value="meStats.favoriteCount" hint="喜欢的店铺与内容" />
        <StatCard label="浏览" :value="meStats.visitCount" hint="最近浏览与使用记录" />
      </div>
    </section>

    <section class="section">
      <SectionTitle eyebrow="Quick Start" title="快捷入口" subtitle="把常用服务直接放在个人中心，不需要登录页。">
        <template #actions>
          <span class="chip">{{ loading ? '加载中' : '游客直达' }}</span>
        </template>
      </SectionTitle>

      <div class="grid-3">
        <article class="card panel me-page__entry">
          <h3>继续逛店</h3>
          <p>从商铺列表直接进入分类和详情页。</p>
          <RouterLink class="btn btn-secondary" to="/shops">打开商铺</RouterLink>
        </article>
        <article class="card panel me-page__entry">
          <h3>阅读博客</h3>
          <p>浏览热门探店和关注流内容。</p>
          <RouterLink class="btn btn-secondary" to="/blogs">打开博客</RouterLink>
        </article>
        <article class="card panel me-page__entry">
          <h3>问 AI</h3>
          <p>让助手帮你挑店、看券和做对比。</p>
          <RouterLink class="btn btn-secondary" to="/ai">打开 AI</RouterLink>
        </article>
      </div>
    </section>

    <section class="section">
      <SectionTitle eyebrow="Status" title="服务状态" subtitle="当前页面是游客态服务中心，不提供独立登录页。" />

      <div class="grid-2">
        <article class="card panel me-page__info">
          <p class="me-page__info-label">当前用户</p>
          <h3 class="me-page__info-title">{{ profile.nickName || '黑马游客' }}</h3>
          <p class="me-page__info-copy">
            {{ profile.bio || '你可以直接浏览店铺、博客和 AI 助手。' }}
          </p>
        </article>

        <article class="card panel me-page__info">
          <p class="me-page__info-label">今日状态</p>
          <h3 class="me-page__info-title">{{ signedLabel }}</h3>
          <p class="me-page__info-copy">{{ notice || '点击签到按钮就能记录一次服务行为。' }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import ProfileCard from '@/components/ProfileCard.vue';
import SectionTitle from '@/components/SectionTitle.vue';
import StatCard from '@/components/StatCard.vue';
import { loadSignCount, loadUserSummary, recordSignIn } from '@/lib/catalog.js';
import { mockMeStats, mockUserProfile } from '@/lib/mock-data.js';

const loading = ref(true);
const signing = ref(false);
const profile = ref(mockUserProfile);
const signCount = ref(mockMeStats.signStreak);
const meStats = ref({ ...mockMeStats });
const notice = ref('');

const signedLabel = computed(() => `连续签到 ${signCount.value} 天`);
const profileStats = computed(() => [
  { label: '城市', value: profile.value.city || '未设置', hint: '个人资料中的城市信息' },
  { label: '级别', value: profile.value.level || '游客', hint: '服务台当前身份' },
  { label: '关注', value: meStats.value.followingCount, hint: '关注的店铺和内容' },
]);

async function loadPage() {
  loading.value = true;
  try {
    const [summary, streak] = await Promise.all([loadUserSummary(), loadSignCount()]);
    profile.value = summary || mockUserProfile;
    signCount.value = typeof streak === 'number' ? streak : mockMeStats.signStreak;
    meStats.value = { ...mockMeStats };
  } finally {
    loading.value = false;
  }
}

async function handleSign() {
  if (signing.value) {
    return;
  }

  signing.value = true;
  notice.value = '';
  try {
    const result = await recordSignIn();
    signCount.value += 1;
    notice.value = result.source === 'remote' ? '已同步签到到后端。' : '已在本地记录一次签到。';
  } finally {
    signing.value = false;
  }
}

onMounted(loadPage);
</script>

<style scoped>
.me-page__entry,
.me-page__info {
  padding: 18px;
  border-radius: 22px;
  display: grid;
  gap: 12px;
}

.me-page__entry h3,
.me-page__info-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 900;
}

.me-page__entry p,
.me-page__info-copy {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.7;
}

.me-page__info-label {
  margin: 0;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
</style>
