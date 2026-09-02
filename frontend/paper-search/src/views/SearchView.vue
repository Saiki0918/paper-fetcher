<template>
  <main class="search-page">
    <section class="search-shell" aria-labelledby="search-title">
      <div class="brand-mark">P</div>
      <p class="eyebrow">开放学术检索</p>
      <h1 id="search-title">找到支撑你下一个想法的论文。</h1>

      <form class="search-form" @submit.prevent="submitSearch">
        <label class="sr-only" for="keyword">搜索论文</label>
        <input
          id="keyword"
          v-model="keyword"
          type="search"
          placeholder="例如：机器学习、气候政策"
          autocomplete="off"
        />
        <button type="submit" :disabled="!keyword.trim()">搜索论文</button>
      </form>

      <div class="search-hints" aria-label="示例搜索词">
        <span>试试这些主题</span>
        <button type="button" @click="keyword = 'machine learning'">machine learning</button>
        <button type="button" @click="keyword = 'climate policy'">climate policy</button>
        <button type="button" @click="keyword = 'computer vision'">computer vision</button>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const keyword = ref('')

// 校验关键词后跳转到结果页，并通过路由查询参数传递搜索词。
function submitSearch() {
  const query = keyword.value.trim()

  if (!query) {
    return
  }

  void router.push({ name: 'papers', query: { q: query } })
}
</script>


<style scoped>
.search-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px 20px;
  background: #f5f7f8;
}

.search-shell {
  width: min(760px, 100%);
  padding: 28px 0 48px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  margin-bottom: 42px;
  border-radius: 10px;
  background: #1c6b63;
  color: #ffffff;
  font-size: 1.25rem;
  font-weight: 800;
}

.eyebrow {
  margin: 0 0 16px;
  color: #1c6b63;
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.12em;
}

h1 {
  max-width: 680px;
  margin: 0;
  color: #142321;
  font-size: clamp(2.4rem, 6vw, 4.8rem);
  line-height: 1.02;
  letter-spacing: 0;
}

.search-form {
  display: flex;
  gap: 10px;
  margin-top: 28px;
  padding: 7px;
  border: 1px solid #d5dfdd;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 8px 28px rgb(20 35 33 / 7%);
}

input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  padding: 12px 14px;
  color: #142321;
  font: inherit;
}

input::placeholder {
  color: #9aa9a6;
}

button {
  border: 0;
  border-radius: 8px;
  padding: 0 18px;
  background: #1c6b63;
  color: #ffffff;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  white-space: nowrap;
}

button:hover:not(:disabled) {
  background: #15564f;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.search-hints {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  color: #82908d;
  font-size: 0.88rem;
}

.search-hints button {
  padding: 4px 10px;
  border: 1px solid #d7e1df;
  border-radius: 999px;
  background: transparent;
  color: #49635f;
  font-size: 0.83rem;
  font-weight: 600;
}

.search-hints button:hover {
  border-color: #1c6b63;
  background: #e7f1ef;
  color: #15564f;
}

@media (max-width: 560px) {
  .search-shell {
    padding-top: 8px;
  }

  .brand-mark {
    margin-bottom: 64px;
  }

  .search-form {
    flex-direction: column;
  }

  .search-form button {
    min-height: 46px;
  }
}
</style>
