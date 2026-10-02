<script setup lang="ts">
defineProps<{ eyebrow?: string; title: string; description?: string }>();
</script>

<template>
  <header class="am-page-head">
    <div>
      <div v-if="eyebrow" class="am-page-eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="am-page-actions"><slot></slot></div>
  </header>
</template>

<style scoped>
.am-page-head {
  display: flex;
  gap: 18px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}

.am-page-eyebrow {
  font-size: 11px;
  font-weight: 800;
  color: var(--am-primary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

h1 {
  margin: 4px 0 5px;
  font-size: 30px;
  line-height: 1.1;
  letter-spacing: -0.03em;
}

p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--am-muted);
}

.am-page-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

@media (max-width: 700px) {
  .am-page-head {
    flex-direction: column;
  }

  h1 {
    font-size: 26px;
  }
}
</style>
