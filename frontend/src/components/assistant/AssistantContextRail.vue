<template>
  <aside class="assistant-rail">
    <section class="assistant-rail__hero card panel">
      <div>
        <p class="assistant-rail__eyebrow">{{ railBadge }}</p>
        <h3 class="assistant-rail__title">{{ railTitle }}</h3>
        <p class="assistant-rail__copy">{{ railCopy }}</p>
      </div>
      <span class="assistant-rail__status">{{ railStatus }}</span>
    </section>

    <section v-if="mode === 'flow'" class="assistant-rail__panel card panel">
      <p class="assistant-rail__eyebrow">Execution Flow</p>
      <h3 class="assistant-rail__title">{{ flowTitle }}</h3>
      <p class="assistant-rail__copy">{{ flowSummary }}</p>

      <div class="assistant-rail__flow">
        <article
          v-for="(step, index) in flowSteps"
          :key="`${step.title}-${index}`"
          :class="['assistant-rail__flow-step', step.active && 'assistant-rail__flow-step--active']"
        >
          <span class="assistant-rail__flow-index">{{ index + 1 }}</span>
          <div class="assistant-rail__flow-copy">
            <strong>{{ step.title }}</strong>
            <span>{{ step.description }}</span>
          </div>
          <span class="assistant-rail__flow-badge">{{ step.badge }}</span>
        </article>
      </div>

      <div v-if="flowPrompts.length" class="assistant-rail__chips">
        <button
          v-for="item in flowPrompts"
          :key="item"
          class="chip chip--active"
          type="button"
          @click="$emit('prompt', item)"
        >
          {{ item }}
        </button>
      </div>
    </section>

    <section class="assistant-rail__panel card panel">
      <p class="assistant-rail__eyebrow">Current context</p>
      <h3 class="assistant-rail__title">{{ contextTitle }}</h3>
      <p class="assistant-rail__copy">{{ contextSummary }}</p>

      <div v-if="contextPills.length" class="assistant-rail__chips">
        <span v-for="item in contextPills" :key="item" class="chip">{{ item }}</span>
      </div>
    </section>

    <section v-if="snapshot.nextSteps.length" class="assistant-rail__panel card panel">
      <div class="assistant-rail__head">
        <h4 class="assistant-rail__subtitle">继续追问</h4>
      </div>
      <div class="assistant-rail__chips">
        <button
          v-for="item in snapshot.nextSteps"
          :key="item"
          class="chip chip--active"
          type="button"
          @click="$emit('prompt', item)"
        >
          {{ item }}
        </button>
      </div>
    </section>

    <section v-if="snapshot.shops.length" class="assistant-rail__panel card panel">
      <div class="assistant-rail__head">
        <h4 class="assistant-rail__subtitle">推荐店铺</h4>
      </div>
      <div class="assistant-rail__list">
        <RouterLink
          v-for="shop in snapshot.shops.slice(0, 3)"
          :key="shop.id"
          :to="`/shops/${shop.id}`"
          class="assistant-rail__item"
        >
          <div class="assistant-rail__item-copy">
            <strong>{{ shop.name }}</strong>
            <span>{{ shop.metaText || shop.area || '' }}</span>
          </div>
          <span class="assistant-rail__item-value">{{ shop.priceText || '' }}</span>
        </RouterLink>
      </div>
    </section>

    <section v-if="snapshot.vouchers.length" class="assistant-rail__panel card panel">
      <div class="assistant-rail__head">
        <h4 class="assistant-rail__subtitle">优惠券</h4>
      </div>
      <div class="assistant-rail__list">
        <article v-for="voucher in snapshot.vouchers.slice(0, 3)" :key="voucher.id" class="assistant-rail__voucher">
          <div>
            <strong>{{ voucher.title }}</strong>
            <p>{{ voucher.shopName || '店铺券' }}</p>
          </div>
          <span>{{ voucher.payText }}</span>
        </article>
      </div>
    </section>

    <section v-if="snapshot.cards.length" class="assistant-rail__panel card panel">
      <div class="assistant-rail__head">
        <h4 class="assistant-rail__subtitle">卡片内容</h4>
      </div>
      <div class="assistant-rail__list">
        <article v-for="card in snapshot.cards.slice(0, 3)" :key="card.title || card.label" class="assistant-rail__card">
          <strong>{{ card.title || card.label }}</strong>
          <p>{{ card.subtitle || card.desc || card.text || '' }}</p>
        </article>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

const props = defineProps({
  context: {
    type: Object,
    default: () => ({}),
  },
  snapshot: {
    type: Object,
    default: () => ({ suggestions: [], shops: [], vouchers: [], cards: [], nextSteps: [] }),
  },
  mode: {
    type: String,
    default: 'context',
  },
});

defineEmits(['prompt']);

const contextTitle = computed(() => {
  return (
    props.context.shopName ||
    props.context.blogTitle ||
    props.context.typeName ||
    props.context.page ||
    '本地生活'
  );
});

const contextSummary = computed(() => {
  const parts = [];
  if (props.context.page) parts.push(`来自 ${props.context.page} 页面`);
  if (props.context.area) parts.push(props.context.area);
  if (props.context.typeName) parts.push(props.context.typeName);
  if (props.context.blogTitle) parts.push(props.context.blogTitle);
  if (props.context.shopName) parts.push(props.context.shopName);
  return parts.length ? parts.join(' · ') : 'AI 会根据当前上下文给出店铺、优惠券和对比建议。';
});

const contextPills = computed(() => {
  return [props.context.typeName, props.context.area, props.context.shopName, props.context.blogTitle]
    .filter(Boolean)
    .slice(0, 4);
});

const flowTitle = computed(() => {
  if (props.context.shopName) {
    return '店铺分析流程';
  }
  if (props.context.blogTitle) {
    return '博客阅读流程';
  }
  if (props.context.typeName) {
    return '分类推荐流程';
  }
  return '通用推荐流程';
});

const railTitle = computed(() => {
  if (props.mode === 'flow') {
    return '执行流程';
  }

  return '知识图谱';
});

const railBadge = computed(() => {
  return props.mode === 'flow' ? 'FLOW PANEL' : 'GRAPH PANEL';
});

const railStatus = computed(() => {
  return props.mode === 'flow' ? 'FLOW' : 'GRAPH';
});

const railCopy = computed(() => {
  if (props.mode === 'flow') {
    return '当前会话的分析步骤、追问和推荐节点会按执行路径展开。';
  }

  return '当前上下文会聚合店铺、博客、分类和优惠券信息，供 AI 联想和关联推荐。';
});

const flowSummary = computed(() => {
  return '当前会话的处理步骤会按照“理解问题、结合上下文、给出建议、等待追问”的节奏展开。';
});

const flowSteps = computed(() => {
  const source = Array.isArray(props.snapshot?.taskChain) && props.snapshot.taskChain.length
    ? props.snapshot.taskChain
    : Array.isArray(props.snapshot?.nextSteps) && props.snapshot.nextSteps.length
      ? props.snapshot.nextSteps.map((item) => ({ title: item, description: 'AI 会围绕这个方向继续展开。' }))
      : [];

  const baseSteps = source.length
    ? source.map((item, index) => ({
        title: item.title || item.label || item,
        description: item.description || item.subtitle || item.desc || '正在处理这一阶段。',
        badge: item.status || item.badge || '进行中',
        active: Boolean(item.active) || index === source.length - 1,
      }))
    : [
        { title: '理解问题', description: '读取你的提问和上下文。', badge: '完成', active: true },
        { title: '整理线索', description: '匹配店铺、博客或优惠券内容。', badge: '进行中', active: false },
        { title: '生成建议', description: '输出可直接执行的答案。', badge: '待办', active: false },
      ];

  return baseSteps.slice(0, 4);
});

const flowPrompts = computed(() => {
  if (Array.isArray(props.snapshot?.nextSteps) && props.snapshot.nextSteps.length) {
    return props.snapshot.nextSteps.slice(0, 3);
  }

  return props.snapshot?.suggestions?.length ? props.snapshot.suggestions.map((item) => item.prompt).slice(0, 3) : [];
});
</script>

<style scoped>
.assistant-rail {
  display: grid;
  gap: 14px;
  min-width: 0;
  position: sticky;
  top: 20px;
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding-right: 4px;
}

.assistant-rail__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-radius: 24px;
}

.assistant-rail__panel {
  display: grid;
  gap: 14px;
  padding: 16px;
  border-radius: 24px;
}

.assistant-rail__status {
  flex: none;
  padding: 7px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-soft);
  color: var(--primary-strong);
  font-size: 0.72rem;
  font-weight: 850;
}

.assistant-rail__flow {
  display: grid;
  gap: 10px;
}

.assistant-rail__flow-step {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding: 12px 14px;
  border-radius: 18px;
  background: var(--surface-muted);
  border: 1px solid var(--line);
}

.assistant-rail__flow-step--active {
  background: var(--primary-soft);
  border-color: var(--primary-soft);
}

.assistant-rail__flow-index {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--surface-strong);
  border: 1px solid var(--line);
  color: var(--text-soft);
  font-weight: 850;
}

.assistant-rail__flow-copy {
  min-width: 0;
}

.assistant-rail__flow-copy strong {
  display: block;
  font-size: 0.92rem;
  font-weight: 850;
}

.assistant-rail__flow-copy span {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  line-height: 1.55;
  font-size: 0.78rem;
}

.assistant-rail__flow-badge {
  flex: none;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--surface-strong);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 800;
}

.assistant-rail__eyebrow {
  margin: 0;
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 850;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.assistant-rail__title {
  margin: 0;
  font-size: 1.02rem;
  font-weight: 900;
}

.assistant-rail__copy {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.7;
}

.assistant-rail__subtitle {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 850;
}

.assistant-rail__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.assistant-rail__list {
  display: grid;
  gap: 10px;
}

.assistant-rail__item,
.assistant-rail__voucher,
.assistant-rail__card {
  padding: 14px;
  border-radius: 18px;
  background: var(--surface-muted);
  border: 1px solid var(--line);
}

.assistant-rail__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.assistant-rail__item-copy,
.assistant-rail__voucher div {
  min-width: 0;
}

.assistant-rail__item-copy strong,
.assistant-rail__voucher strong,
.assistant-rail__card strong {
  display: block;
  font-size: 0.92rem;
  font-weight: 850;
}

.assistant-rail__item-copy span,
.assistant-rail__voucher p,
.assistant-rail__card p {
  display: block;
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 0.78rem;
  line-height: 1.55;
}

.assistant-rail__item-value {
  flex: none;
  color: var(--primary-strong);
  font-weight: 850;
}

.assistant-rail__voucher {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 10px;
}

.assistant-rail__voucher span {
  flex: none;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-strong);
  border: 1px solid var(--primary-soft);
  font-size: 0.8rem;
  font-weight: 850;
}
</style>
