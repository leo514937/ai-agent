<template>
  <div class="page fade-in">
    <EmptyState
      glyph="404"
      title="页面不存在"
      description="你访问的路径没有对应页面，返回首页继续浏览服务。"
      action-label="回到首页"
      @action="goHome"
    />
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router';
import EmptyState from '@/components/EmptyState.vue';

const router = useRouter();

function goHome() {
  router.push('/');
}
</script>
