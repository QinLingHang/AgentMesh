<script setup lang="ts">
defineProps<{ title: string; description?: string }>();
</script>
<template>
  <div class="am-empty">
    <div>
      <div
        style="margin-bottom: 8px; font-size: 28px; color: var(--am-primary)"
      >
        ◇
      </div>
      <strong style="color: var(--am-text)">{{ title }}</strong>
      <div v-if="description" style="margin-top: 5px; font-size: 12px">
        {{ description }}
      </div>
      <div style="margin-top: 12px"><slot></slot></div>
    </div>
  </div>
</template>
