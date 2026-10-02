<script setup lang="ts">
const props = withDefaults(defineProps<{ status?: string }>(), { status: '' });
function tone(value: string): 'danger' | 'info' | 'success' | 'warning' {
  const upper = value.toUpperCase();
  if (['ACTIVE', 'COMPLETED', 'ENABLED', 'READY', 'SUCCESS'].includes(upper))
    return 'success';
  if (['CANCELED', 'DENIED', 'ERROR', 'FAILED', 'FAILURE'].includes(upper))
    return 'danger';
  if (
    [
      'AUTH_REQUIRED',
      'INDEXING',
      'INPUT_REQUIRED',
      'QUEUED',
      'RUNNING',
      'UPLOADED',
    ].includes(upper)
  )
    return 'warning';
  return 'info';
}
</script>
<template>
  <el-tag size="small" round effect="light" :type="tone(props.status)">
    {{ props.status }}
  </el-tag>
</template>
