<script setup lang="ts">
import { useConversationsStore } from '@/stores/conversations'
import { formatTime } from '@/utils/format'
import type { Conversation } from '@/types'

const props = defineProps<{ conv: Conversation; active: boolean }>()
const emit = defineEmits<{ select: [id: string]; contextmenu: [e: MouseEvent, id: string] }>()
</script>

<template>
  <div
    class="conv-item"
    :class="{ active: props.active }"
    @click="emit('select', props.conv.id)"
    @contextmenu.prevent="emit('contextmenu', $event, props.conv.id)"
  >
    <div class="conv-content">
      <span class="conv-icon">💬</span>
      <div class="conv-info">
        <span class="conv-title">{{ props.conv.title || '新对话' }}</span>
        <span class="conv-time">{{ formatTime(props.conv.updatedAt) }}</span>
      </div>
    </div>
  </div>
</template>
