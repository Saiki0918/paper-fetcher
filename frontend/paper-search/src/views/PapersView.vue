<template>
  <main class="papers-page">
    <header class="topbar">
      <RouterLink class="brand" :to="{ name: 'search' }">
        <span class="brand-mark">P</span>
        <span>Paper Search</span>
      </RouterLink>
      <RouterLink class="new-search" :to="{ name: 'search' }">New search</RouterLink>
    </header>

    <section class="results-shell" aria-labelledby="results-title">
      <div class="results-heading">
        <div>
          <p class="eyebrow">OPENALEX RESULTS</p>
          <h1 id="results-title">Papers for “{{ query }}”</h1>
        </div>
        <p v-if="meta" class="result-count">{{ formatNumber(meta.total) }} results</p>
      </div>

      <div v-if="loading" class="state-panel" role="status">
        <span class="loader" aria-hidden="true"></span>
        <span>Searching OpenAlex…</span>
      </div>

      <div v-else-if="errorMessage" class="state-panel error-panel" role="alert">
        <strong>Search unavailable</strong>
        <span>{{ errorMessage }}</span>
        <button type="button" class="retry-button" @click="loadPapers">Try again</button>
      </div>

      <div v-else-if="!papers.length" class="state-panel">
        <strong>No papers found</strong>
        <span>Try a broader keyword or search in English.</span>
      </div>

      <div v-else class="paper-list">
        <article v-for="paper in papers" :key="paper.id" class="paper-card">
          <div class="paper-card-main">
            <div class="paper-meta">
              <span>{{ paper.source || 'Unknown source' }}</span>
              <span v-if="paper.year">{{ paper.year }}</span>
            </div>
            <h2>
              <a :href="paper.url" target="_blank" rel="noopener noreferrer">{{ paper.title }}</a>
            </h2>
            <p class="authors">{{ formatAuthors(paper.authors) || '作者信息暂无' }}</p>
            <p v-if="paper.abstract" class="abstract">{{ paper.abstract }}</p>
            <p v-else class="abstract abstract-empty">暂无摘要</p>
          </div>
          <div class="paper-card-stats">
            <div class="stat-block">
              <span class="stat-label">CITATIONS</span>
              <strong>{{ formatNumber(paper.citationCount) }}</strong>
            </div>
            <div class="stat-block">
              <span class="stat-label">DOWNLOADS</span>
              <strong>{{ formatNumber(paper.downloadCount) }}</strong>
            </div>
            <span v-if="paper.isOpenAccess" class="oa-label">Open access</span>
          </div>
        </article>
      </div>

      <nav v-if="meta && papers.length" class="pagination" aria-label="Pagination">
        <button type="button" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
          Previous
        </button>
        <span>Page {{ currentPage }} of {{ totalPages }}</span>
        <button type="button" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
          Next
        </button>
      </nav>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { searchPapers } from '@/services/api'
import type { Paper, PaperSearchMeta } from '@/types/paper'

const route = useRoute()
const router = useRouter()
const papers = ref<Paper[]>([])
const meta = ref<PaperSearchMeta | null>(null)
const loading = ref(false)
const errorMessage = ref('')

const query = computed(() => {
  const value = route.query.q
  return typeof value === 'string' ? value.trim() : ''
})

const totalPages = computed(() => {
  if (!meta.value || meta.value.total === 0) return 1
  return Math.ceil(meta.value.total / meta.value.pageSize)
})

const currentPage = computed(() => meta.value?.page ?? 1)

async function loadPapers() {
  if (!query.value) {
    void router.replace({ name: 'search' })
    return
  }

  loading.value = true
  errorMessage.value = ''

  try {
    const requestedPage = Number(route.query.page) || 1
    const response = await searchPapers(query.value, requestedPage)
    papers.value = response.data
    meta.value = response.meta
    if (response.error) errorMessage.value = response.error.message
  } catch (error) {
    papers.value = []
    meta.value = null
    errorMessage.value = error instanceof Error ? error.message : '搜索请求失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  void router.push({ name: 'papers', query: { q: query.value, page: String(page) } })
}

function formatNumber(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString()
}

function formatAuthors(authors: string[]) {
  if (authors.length <= 3) return authors.join(', ')
  return `${authors.slice(0, 3).join(', ')} 等 ${authors.length} 位作者`
}

watch([query, () => route.query.page], loadPapers, { immediate: true })
</script>

<style scoped>
.papers-page {
  min-height: 100vh;
  background: #f5f7f8;
  color: #142321;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: min(1120px, calc(100% - 40px));
  min-height: 76px;
  margin: 0 auto;
  border-bottom: 1px solid #dfe8e5;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #142321;
  font-weight: 800;
  text-decoration: none;
}

.brand-mark {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: #1c6b63;
  color: #ffffff;
  font-size: 0.95rem;
}

.new-search,
.retry-button {
  border: 1px solid #c9d9d5;
  border-radius: 7px;
  padding: 8px 12px;
  background: #ffffff;
  color: #1c6b63;
  cursor: pointer;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  text-decoration: none;
}

.new-search:hover,
.retry-button:hover {
  border-color: #1c6b63;
  background: #e7f1ef;
}

.results-shell {
  width: min(1120px, calc(100% - 40px));
  margin: 0 auto;
  padding: 52px 0 72px;
}

.results-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
}

.eyebrow {
  margin: 0 0 10px;
  color: #1c6b63;
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.12em;
}

h1 {
  margin: 0;
  font-size: clamp(1.8rem, 3vw, 2.8rem);
  line-height: 1.12;
  letter-spacing: 0;
}

.result-count {
  margin: 0 0 4px;
  color: #71817e;
  font-size: 0.9rem;
  white-space: nowrap;
}

.paper-list {
  display: grid;
  gap: 12px;
}

.paper-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 24px;
  padding: 24px;
  border: 1px solid #dce6e3;
  border-radius: 8px;
  background: #ffffff;
}

.paper-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #1c6b63;
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.paper-meta span + span::before {
  margin-right: 8px;
  color: #aab8b5;
  content: '·';
}

h2 {
  margin: 9px 0 7px;
  font-size: 1.18rem;
  line-height: 1.35;
}

h2 a {
  color: #142321;
  text-decoration: none;
}

h2 a:hover {
  color: #1c6b63;
  text-decoration: underline;
}

.authors,
.abstract {
  margin: 0;
  color: #60706e;
  font-size: 0.92rem;
  line-height: 1.55;
}

.abstract {
  display: -webkit-box;
  margin-top: 13px;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.abstract-empty {
  color: #9aa9a6;
  font-style: italic;
}

.paper-card-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  padding-top: 4px;
  border-left: 1px solid #e6eeec;
  color: #60706e;
}

.stat-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.stat-label {
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.1em;
}

.paper-card-stats strong {
  color: #142321;
  font-size: 1.5rem;
}

.oa-label {
  margin-top: 8px;
  color: #1c6b63;
  font-size: 0.75rem;
  font-weight: 700;
}

.state-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
  min-height: 220px;
  padding: 28px;
  border: 1px dashed #cbdad6;
  border-radius: 8px;
  background: #ffffff;
  color: #71817e;
}

.state-panel strong {
  color: #142321;
}

.error-panel {
  flex-direction: column;
}

.loader {
  width: 18px;
  height: 18px;
  border: 2px solid #c9d9d5;
  border-top-color: #1c6b63;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  margin-top: 26px;
  color: #60706e;
  font-size: 0.9rem;
}

.pagination button {
  border: 1px solid #c9d9d5;
  border-radius: 7px;
  padding: 8px 12px;
  background: #ffffff;
  color: #1c6b63;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.pagination button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 700px) {
  .results-heading {
    align-items: start;
    flex-direction: column;
    gap: 8px;
  }

  .paper-card {
    grid-template-columns: 1fr;
  }

  .paper-card-stats {
    align-items: flex-start;
    padding-top: 14px;
    border-top: 1px solid #e6eeec;
    border-left: 0;
  }

  .stat-block {
    align-items: flex-start;
  }
}

@media (max-width: 560px) {
  .topbar,
  .results-shell {
    width: min(100% - 28px, 1120px);
  }

  .results-shell {
    padding-top: 36px;
  }

  .paper-card {
    padding: 18px;
  }
}
</style>
