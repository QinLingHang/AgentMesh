<script setup lang="ts">
defineProps<{
  label: string;
  value: number | string;
  hint?: string;
  tone?: 'danger' | 'default' | 'primary' | 'success';
}>();
</script>

<template>
  <div class="am-card am-metric">
    <div class="am-metric-label">{{ label }}</div>
    <div
      class="am-metric-value"
      :class="tone && tone !== 'default' ? `tone-${tone}` : ''"
    >
      {{ value }}
    </div>
    <div v-if="hint" class="am-metric-hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.am-metric-hint {
  margin-top: 5px;
  font-size: 11px;
  color: var(--am-muted);
}

.tone-success {
  color: var(--am-success);
}

.tone-danger {
  color: var(--am-danger);
}

.tone-primary {
  color: var(--am-primary);
}
</style>
