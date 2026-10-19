<template>
  <main class="papers-page">
    <header class="topbar">
      <RouterLink class="brand" :to="{ name: 'search' }">
        <span class="brand-mark">P</span>
        <span>论文搜索</span>
      </RouterLink>
      <RouterLink class="new-search" :to="{ name: 'search' }">重新搜索</RouterLink>
    </header>

    <section class="results-shell" aria-labelledby="results-title">
      <div class="results-heading">
        <div>
          <p class="eyebrow">{{ formatPlatform(selectedPlatform) }}搜索结果</p>
          <h1 id="results-title">“{{ query }}”的相关论文</h1>
        </div>
        <div class="result-controls">
          <label for="platform">平台</label>
          <!-- 平台选项与路由白名单、显示名称共用配置，新增来源后同步出现在此处。 -->
          <select id="platform" :value="selectedPlatform" @change="changePlatform">
            <option v-for="item in PAPER_PLATFORMS" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
          <label for="access">访问方式</label>
          <select id="access" :value="accessFilter" @change="changeAccessFilter">
            <option value="all">全部</option>
            <option value="openAccess">开放获取</option>
            <option value="hasPdf">有 PDF</option>
            <option value="detailOnly">仅详情页</option>
          </select>
          <p v-if="meta" class="result-count">
            {{ meta.totalIsApproximate ? '约 ' : '' }}{{ formatNumber(meta.total) }} 条结果
          </p>
        </div>
      </div>

      <!-- 部分来源失败仅显示提示，继续渲染其他平台成功返回的结果。 -->
      <p v-if="meta?.failedPlatforms.length" class="source-warning" role="status">
        {{ meta.failedPlatforms.map(formatPlatform).join('、') }} 暂时不可用；
        其余平台的结果仍会显示。
      </p>

      <div v-if="loading" class="state-panel" role="status">
        <span class="loader" aria-hidden="true"></span>
        <span>正在搜索{{ formatPlatform(selectedPlatform) }}…</span>
      </div>

      <div v-else-if="errorMessage" class="state-panel error-panel" role="alert">
        <strong>暂时无法搜索</strong>
        <span>{{ errorMessage }}</span>
        <button type="button" class="retry-button" @click="loadPapers">重试</button>
      </div>

      <div v-else-if="!visiblePapers.length" class="state-panel">
        <strong>没有找到论文</strong>
        <span>{{
          accessFilter === 'all'
            ? '请尝试更宽泛的关键词，或使用英文搜索。'
            : '当前结果中没有符合该访问方式的论文。'
        }}</span>
      </div>

      <div v-else class="paper-list">
        <article v-for="paper in visiblePapers" :key="paper.id" class="paper-card">
          <div class="paper-card-main">
            <div class="paper-meta">
              <span class="platform-label">{{ formatPlatform(paper.platform) }}</span>
              <span>{{ paper.source || '未知来源' }}</span>
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
            <!-- 以实际 pdfUrl 决定按钮是否出现，开放标记本身不能保证存在 PDF。 -->
            <a
              v-if="paper.pdfUrl"
              class="pdf-link"
              :href="paper.pdfUrl"
              target="_blank"
              rel="noopener noreferrer"
            >
              查看 PDF
            </a>
            <div
              class="stat-block"
              :title="
                paper.citationCount == null
                  ? '当前来源未提供引用量，不代表零引用'
                  : '引用量按当前来源的收录范围统计'
              "
            >
              <span class="stat-label">引用量</span>
              <!-- 区分来源未提供的统计与明确返回的 0 次引用。 -->
              <strong>{{
                paper.citationCount == null ? '暂无数据' : formatNumber(paper.citationCount)
              }}</strong>
            </div>
            <span :class="['access-label', `access-${paper.accessType}`]">
              {{ formatAccessType(paper.accessType) }}
            </span>
          </div>
        </article>
      </div>

      <!-- 当前页可能被访问筛选全部隐藏，原始页有记录时仍保留翻页入口。 -->
      <nav v-if="meta && papers.length" class="pagination" aria-label="分页">
        <button type="button" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
          上一页
        </button>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button
          type="button"
          :disabled="currentPage >= totalPages"
          @click="goToPage(currentPage + 1)"
        >
          下一页
        </button>
      </nav>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { searchPapers } from '@/services/api'
import { PAPER_PLATFORMS } from '@/types/paper'
import type {
  AccessFilter,
  Paper,
  PaperAccessType,
  PaperPlatform,
  PaperSearchMeta,
} from '@/types/paper'

const route = useRoute()
const router = useRouter()
const papers = ref<Paper[]>([])
const meta = ref<PaperSearchMeta | null>(null)
const loading = ref(false)
const errorMessage = ref('')

// 请求共用上面的页面状态；编号决定谁有权修改它们，控制器负责取消无用的网络等待。
let latestRequestId = 0
let activeController: AbortController | null = null

// 必须先使编号失效再取消：abort 后旧请求仍会执行 catch 和 finally。
function cancelActiveRequest() {
  latestRequestId += 1
  activeController?.abort()
  activeController = null
}

// 路由查询值可能是数组或空值，只接受单个字符串作为关键词。
const query = computed(() => {
  const value = route.query.q
  return typeof value === 'string' ? value.trim() : ''
})

// 手工修改 URL 或访问旧链接时，未注册的平台统一回退到全部平台。
const selectedPlatform = computed<PaperPlatform>(() => {
  const value = route.query.platform
  return typeof value === 'string' && PAPER_PLATFORMS.some((item) => item.value === value)
    ? (value as PaperPlatform)
    : 'all'
})

// 筛选状态保存在 URL 中，刷新页面和翻页时都可恢复；非法值按全部处理。
const accessFilter = computed<AccessFilter>(() => {
  const value = route.query.access
  return value === 'openAccess' || value === 'hasPdf' || value === 'detailOnly' ? value : 'all'
})

// 目前只筛选后端已返回的当前页，不发送访问参数，也不继续请求其他页补齐数量。
const visiblePapers = computed(() => {
  if (accessFilter.value === 'openAccess') return papers.value.filter((paper) => paper.isOpenAccess)
  if (accessFilter.value === 'hasPdf') return papers.value.filter((paper) => paper.pdfUrl)
  if (accessFilter.value === 'detailOnly') {
    return papers.value.filter((paper) => !paper.isOpenAccess && !paper.pdfUrl)
  }
  return papers.value
})

// 页数按后端原始命中数计算，不是访问筛选后的数量；全平台总数还可能存在重叠。
const totalPages = computed(() => {
  if (!meta.value || meta.value.total === 0) return 1
  return Math.ceil(meta.value.total / meta.value.pageSize)
})

const currentPage = computed(() => meta.value?.page ?? 1)

// 根据当前路由参数向后端请求论文，并更新页面的加载、数据和错误状态。
async function loadPapers() {
  // 即使新关键词为空，也先使旧请求失效，防止跳回搜索页时仍有旧响应回写。
  cancelActiveRequest()
  const requestId = latestRequestId

  if (!query.value) {
    loading.value = false
    void router.replace({ name: 'search' })
    return
  }

  // 已取消的控制器不能复用，每次搜索（包括同条件重试）都创建独立控制器。
  const controller = new AbortController()
  activeController = controller
  loading.value = true
  errorMessage.value = ''

  try {
    const requestedPage = Number(route.query.page) || 1
    // 后端目前接收关键词、平台与页码；访问方式筛选由 visiblePapers 在本地完成。
    const response = await searchPapers(
      query.value,
      selectedPlatform.value,
      requestedPage,
      10,
      controller.signal,
    )
    // 取消不能回滚已经完成的响应；只有最新且未被取消的请求才允许更新结果。
    if (requestId !== latestRequestId || controller.signal.aborted) return

    papers.value = response.data
    meta.value = response.meta
    if (response.error) errorMessage.value = response.error.message
  } catch (error) {
    // 主动取消和旧请求的异常无需提示，也不能清空新请求正在使用的页面数据。
    if (requestId !== latestRequestId || controller.signal.aborted) return

    // 只有当前请求真正失败，才清理结果与分页信息并显示错误。
    papers.value = []
    meta.value = null
    errorMessage.value = error instanceof Error ? error.message : '搜索请求失败，请稍后重试'
  } finally {
    // 旧请求也会执行 finally；不能让它关闭新请求的“正在搜索”或清掉新控制器。
    if (requestId === latestRequestId) {
      loading.value = false
      activeController = null
    }
  }
}

// 将结果页切换到指定页，并保留当前关键词、平台和访问筛选条件。
function goToPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  void router.push({
    name: 'papers',
    query: {
      q: query.value,
      platform: selectedPlatform.value,
      access: accessFilter.value,
      page: String(page),
    },
  })
}

// 切换平台筛选并回到该平台搜索结果的第一页。
function changePlatform(event: Event) {
  const platform = (event.target as HTMLSelectElement).value as PaperPlatform
  void router.push({
    name: 'papers',
    // 省略 page 参数以回到第一页，保留用户已选的访问方式。
    query: { q: query.value, platform, access: accessFilter.value },
  })
}

// 更新本地访问筛选并省略 page 回到第一页；若原先在后续页，页码变化会触发重新取数。
function changeAccessFilter(event: Event) {
  const access = (event.target as HTMLSelectElement).value as AccessFilter
  void router.push({
    name: 'papers',
    query: { q: query.value, platform: selectedPlatform.value, access },
  })
}

// 将可选数字格式化为本地化字符串，缺失值显示为横线。
function formatNumber(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString()
}

// 将作者列表压缩为适合论文卡片展示的一行文本。
function formatAuthors(authors: string[]) {
  if (authors.length <= 3) return authors.join(', ')
  return `${authors.slice(0, 3).join(', ')} 等 ${authors.length} 位作者`
}

// 将内部平台标识转换为用户界面显示名称。
function formatPlatform(platform: PaperPlatform) {
  return PAPER_PLATFORMS.find((item) => item.value === platform)?.label ?? platform
}

// 将内部访问类型转换为论文卡片上的可读标签。
function formatAccessType(accessType: PaperAccessType) {
  const labels: Record<PaperAccessType, string> = {
    openPdf: '开放 PDF',
    pdf: '可查看 PDF',
    open: '开放获取',
    detail: '仅详情页',
  }
  return labels[accessType]
}

// 首次进入和关键词、平台、页码变化时取数；访问筛选本身不在远程请求的监听项中。
watch([query, selectedPlatform, () => route.query.page], loadPapers, { immediate: true })

// 离开结果页时同时失效编号和取消请求，阻止尚未完成的异步流程继续回写页面。
onBeforeUnmount(cancelActiveRequest)
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

.result-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.result-controls label {
  color: #71817e;
  font-size: 0.82rem;
  font-weight: 700;
}

.result-controls select {
  min-height: 34px;
  border: 1px solid #c9d9d5;
  border-radius: 7px;
  padding: 0 28px 0 10px;
  background: #ffffff;
  color: #142321;
  font: inherit;
  font-size: 0.88rem;
}

.result-count {
  margin: 0 0 4px;
  color: #71817e;
  font-size: 0.9rem;
  white-space: nowrap;
}

.source-warning {
  margin: -10px 0 16px;
  color: #8a611a;
  font-size: 0.85rem;
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

.platform-label {
  color: #5c799f;
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

.pdf-link {
  border: 1px solid #9dc4bd;
  border-radius: 6px;
  padding: 5px 8px;
  color: #15564f;
  font-size: 0.75rem;
  font-weight: 800;
  text-decoration: none;
}

.pdf-link:hover {
  background: #e7f1ef;
}

.access-label {
  margin-top: 8px;
  font-size: 0.75rem;
  font-weight: 700;
}

.access-openPdf,
.access-open {
  color: #1c6b63;
}

.access-pdf {
  color: #42668f;
}

.access-detail {
  color: #71817e;
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

  .result-controls {
    justify-content: flex-start;
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
