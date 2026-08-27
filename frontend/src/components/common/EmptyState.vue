<script setup lang="ts">
import { useConversationsStore } from '@/stores/conversations'

const store = useConversationsStore()
</script>

<template>
  <div class="empty-state">
    <div class="empty-hero">
      <div class="hero-icon">📚</div>
      <h1>Paper-Copilot</h1>
      <p class="hero-desc">学术论文检索与整理 Agent 系统</p>
      <div class="hero-features">
        <div class="feature-card">
          <span class="feature-icon">🔍</span>
          <span>智能检索论文知识库</span>
        </div>
        <div class="feature-card">
          <span class="feature-icon">💡</span>
          <span>RAG 增强学术问答</span>
        </div>
        <div class="feature-card">
          <span class="feature-icon">📝</span>
          <span>文献结构化总结</span>
        </div>
      </div>
      <button class="btn-start" @click="store.createConversation()">开始对话</button>
    </div>
  </div>
</template>
