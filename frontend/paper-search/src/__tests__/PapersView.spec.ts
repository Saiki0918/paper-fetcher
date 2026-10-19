import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { searchPapers } from '@/services/api'
import type { PaperPlatform, PaperSearchResponse } from '@/types/paper'
import PapersView from '@/views/PapersView.vue'

// 替换网络边界，保留真实页面和路由交互，测试不依赖后端或第三方平台可用性。
vi.mock('@/services/api', () => ({ searchPapers: vi.fn<typeof searchPapers>() }))

// 每个新增入口都需通过路由、选中状态与结果渲染的同一组验证。
const newPlatforms: PaperPlatform[] = [
  'biorxiv',
  'medrxiv',
  'chemrxiv',
  'researchsquare',
  'osf',
  'psyarxiv',
  'socarxiv',
  'hal',
  'zenodo',
]

/** 构造可翻页、带公开 PDF 但缺少引用统计的统一响应，供各平台复用。 */
function response(platform: PaperPlatform): PaperSearchResponse {
  return {
    data: [
      {
        id: `${platform}:123`,
        platform,
        title: 'A preprint',
        year: 2025,
        authors: ['A. Author'],
        abstract: 'Summary',
        source: 'Preprint',
        doi: null,
        url: 'https://example.org/paper',
        citationCount: null,
        isOpenAccess: true,
        pdfUrl: 'https://example.org/paper.pdf',
        accessType: 'openPdf',
      },
    ],
    meta: {
      query: 'machine learning',
      page: 1,
      pageSize: 10,
      total: 21,
      requestedPlatform: platform,
      searchedPlatforms: [],
      totalIsApproximate: false,
      failedPlatforms: [],
    },
    error: null,
  }
}

// 手动控制完成顺序；即使收到取消信号仍可返回，用于验证取消之外的编号保护。
function pendingSearch() {
  let resolve!: (value: PaperSearchResponse) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<PaperSearchResponse>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

/** 使用内存路由进入结果页，并等待页面初次监听触发的异步加载完成。 */
async function render(platform: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { name: 'papers', path: '/papers', component: PapersView },
      { name: 'search', path: '/', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'papers', query: { q: 'machine learning', platform } })
  await router.isReady()
  const wrapper = mount(PapersView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  // 隔离各用例的调用记录和临时返回值，默认按请求中的平台生成相应结果。
  vi.mocked(searchPapers).mockReset()
  vi.mocked(searchPapers).mockImplementation(async (_query, platform = 'all') => response(platform))
})

describe('preprint platform search', () => {
  // 防止新平台只出现在下拉框中，却被路由校验回退为 all 或丢失 PDF 按钮。
  it.each(newPlatforms)('accepts %s from the route and renders its results', async (platform) => {
    const { wrapper } = await render(platform)
    expect(searchPapers).toHaveBeenCalledWith(
      'machine learning',
      platform,
      1,
      10,
      expect.any(AbortSignal),
    )
    expect((wrapper.get('#platform').element as HTMLSelectElement).value).toBe(platform)
    expect(wrapper.find('.paper-card').text()).toContain('A preprint')
    expect(wrapper.get('.pdf-link').attributes('href')).toBe('https://example.org/paper.pdf')
    wrapper.unmount()
  })

  // 切换平台应从第一页请求，随后翻页仍使用同一平台，而不是恢复为全平台搜索。
  it('switches to a new platform and preserves it during pagination', async () => {
    const { wrapper, router } = await render('all')
    for (const platform of newPlatforms) {
      expect(wrapper.find(`option[value="${platform}"]`).exists()).toBe(true)
    }
    await wrapper.get('#platform').setValue('socarxiv')
    await flushPromises()
    expect(router.currentRoute.value.query.platform).toBe('socarxiv')
    expect(searchPapers).toHaveBeenLastCalledWith(
      'machine learning',
      'socarxiv',
      1,
      10,
      expect.any(AbortSignal),
    )
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()
    expect(searchPapers).toHaveBeenLastCalledWith(
      'machine learning',
      'socarxiv',
      2,
      10,
      expect.any(AbortSignal),
    )
    wrapper.unmount()
  })

  // 聚合搜索的局部失败需要显示平台名称，不能直接暴露难以理解的内部标识。
  it('shows readable labels for failures from the added platforms', async () => {
    const payload = response('all')
    payload.meta.failedPlatforms = ['biorxiv', 'psyarxiv', 'zenodo']
    vi.mocked(searchPapers).mockResolvedValue(payload)
    const { wrapper } = await render('all')
    expect(wrapper.get('.source-warning').text()).toContain(
      'bioRxiv（Europe PMC 索引）、PsyArXiv、Zenodo 预印本',
    )
    wrapper.unmount()
  })

  // 手动输入非法 URL 参数时，页面应回退到合法请求，避免把无效平台传给后端。
  it('uses all platforms for an unsupported route value', async () => {
    const { wrapper } = await render('unknown')
    expect(searchPapers).toHaveBeenCalledWith(
      'machine learning',
      'all',
      1,
      10,
      expect.any(AbortSignal),
    )
    wrapper.unmount()
  })

  // 两张卡片分别覆盖未知引用量与真实 0；缺少 PDF 的卡片仍保留可点击的详情入口。
  it('distinguishes a missing citation count from a real zero and hides absent PDFs', async () => {
    const payload = response('chemrxiv')
    payload.data.push({
      ...payload.data[0]!,
      id: 'chemrxiv:456',
      title: 'A preprint without a PDF link',
      citationCount: 0,
      pdfUrl: null,
      accessType: 'open',
    })
    vi.mocked(searchPapers).mockResolvedValue(payload)
    const { wrapper } = await render('chemrxiv')
    const cards = wrapper.findAll('.paper-card')
    expect(cards[0]!.get('.stat-block strong').text()).toBe('暂无数据')
    expect(cards[1]!.get('.stat-block strong').text()).toBe('0')
    expect(cards[1]!.find('.pdf-link').exists()).toBe(false)
    expect(cards[1]!.get('h2 a').attributes('href')).toBe('https://example.org/paper')
    wrapper.unmount()
  })
})

describe('search request lifecycle', () => {
  // 三种远程搜索条件都必须取消旧请求，并防止晚返回的旧结果覆盖新结果和分页。
  it.each(['platform', 'keyword', 'page'] as const)(
    'keeps the latest results when %s changes and the old response arrives last',
    async (changedField) => {
      const oldSearch = pendingSearch()
      const newSearch = pendingSearch()
      vi.mocked(searchPapers)
        .mockReturnValueOnce(oldSearch.promise)
        .mockReturnValueOnce(newSearch.promise)
      const { wrapper, router } = await render('all')
      const oldSignal = vi.mocked(searchPapers).mock.calls[0]![4]!

      await router.push({
        name: 'papers',
        query: {
          q: changedField === 'keyword' ? 'deep learning' : 'machine learning',
          platform: changedField === 'platform' ? 'biorxiv' : 'all',
          page: changedField === 'page' ? '2' : '1',
        },
      })
      await flushPromises()
      const newSignal = vi.mocked(searchPapers).mock.calls[1]![4]!
      expect(oldSignal.aborted).toBe(true)
      expect(newSignal).not.toBe(oldSignal)
      expect(newSignal.aborted).toBe(false)

      const latest = response(changedField === 'platform' ? 'biorxiv' : 'all')
      latest.data[0]!.title = 'Latest search result'
      latest.meta.page = changedField === 'page' ? 2 : 1
      newSearch.resolve(latest)
      await flushPromises()

      const stale = response('all')
      stale.data[0]!.title = 'Stale search result'
      oldSearch.resolve(stale)
      await flushPromises()
      expect(wrapper.get('.paper-card h2').text()).toBe('Latest search result')
      expect(wrapper.get('.pagination span').text()).toBe(`第 ${latest.meta.page} / 3 页`)
      expect(wrapper.find('.loader').exists()).toBe(false)
      expect(wrapper.find('.error-panel').exists()).toBe(false)
      wrapper.unmount()
    },
  )

  // 旧请求的 catch/finally 既不能提前结束新请求的加载，也不能清空已显示的新结果。
  it.each(['pending', 'completed'] as const)(
    'ignores an old failure while the latest search is %s',
    async (latestState) => {
      const oldSearch = pendingSearch()
      const newSearch = pendingSearch()
      vi.mocked(searchPapers)
        .mockReturnValueOnce(oldSearch.promise)
        .mockReturnValueOnce(newSearch.promise)
      const { wrapper } = await render('all')
      await wrapper.get('#platform').setValue('biorxiv')
      await flushPromises()

      if (latestState === 'completed') {
        newSearch.resolve(response('biorxiv'))
        await flushPromises()
      }
      oldSearch.reject(new Error('Old search failed'))
      await flushPromises()
      expect(wrapper.find('.error-panel').exists()).toBe(false)
      expect(wrapper.find('.loader').exists()).toBe(latestState === 'pending')

      if (latestState === 'pending') {
        newSearch.resolve(response('biorxiv'))
        await flushPromises()
      }
      expect(wrapper.get('.paper-card .platform-label').text()).toContain('bioRxiv')
      expect(wrapper.find('.loader').exists()).toBe(false)
      expect(wrapper.find('.error-panel').exists()).toBe(false)
      wrapper.unmount()
    },
  )

  // 模拟 fetch 收到 abort 后立即拒绝，确认主动取消不会被当成当前搜索失败。
  it('keeps loading the new search when abort rejects the previous one', async () => {
    const oldSearch = pendingSearch()
    const newSearch = pendingSearch()
    vi.mocked(searchPapers)
      .mockImplementationOnce((_query, _platform, _page, _pageSize, signal) => {
        signal!.addEventListener(
          'abort',
          () => oldSearch.reject(new DOMException('Request cancelled', 'AbortError')),
          { once: true },
        )
        return oldSearch.promise
      })
      .mockReturnValueOnce(newSearch.promise)
    const { wrapper } = await render('all')
    await wrapper.get('#platform').setValue('medrxiv')
    await flushPromises()
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.error-panel').exists()).toBe(false)

    newSearch.resolve(response('medrxiv'))
    await flushPromises()
    expect(wrapper.get('.paper-card .platform-label').text()).toContain('medRxiv')
    expect(wrapper.find('.error-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  // 空关键词先取消旧请求再跳转，避免早退分支绕过取消和状态失效处理。
  it('cancels a pending search when the keyword becomes empty', async () => {
    const search = pendingSearch()
    vi.mocked(searchPapers).mockReturnValueOnce(search.promise)
    const { wrapper, router } = await render('all')
    const signal = vi.mocked(searchPapers).mock.calls[0]![4]!
    await router.push({ name: 'papers', query: { q: ' ', platform: 'all' } })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(router.currentRoute.value.name).toBe('search')

    search.resolve(response('all'))
    await flushPromises()
    expect(wrapper.find('.paper-card').exists()).toBe(false)
    expect(wrapper.find('.loader').exists()).toBe(false)
    expect(wrapper.find('.error-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  // 离开页面后，尚未结束的请求需要收到取消信号，晚到的异常也应被安全处理。
  it('cancels a pending search when the results page unmounts', async () => {
    const search = pendingSearch()
    vi.mocked(searchPapers).mockReturnValueOnce(search.promise)
    const { wrapper } = await render('all')
    const signal = vi.mocked(searchPapers).mock.calls[0]![4]!
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    search.reject(new DOMException('Request cancelled', 'AbortError'))
    await flushPromises()
  })

  // 当前请求的真实失败仍需提示，并允许在条件不变时用新的信号重试。
  it('shows a current failure and can retry with a fresh controller', async () => {
    const retry = pendingSearch()
    vi.mocked(searchPapers)
      .mockRejectedValueOnce(new Error('Current search failed'))
      .mockReturnValueOnce(retry.promise)
    const { wrapper } = await render('all')
    const firstSignal = vi.mocked(searchPapers).mock.calls[0]![4]!
    expect(wrapper.get('.error-panel').text()).toContain('Current search failed')
    expect(wrapper.find('.loader').exists()).toBe(false)

    await wrapper.get('.retry-button').trigger('click')
    const retrySignal = vi.mocked(searchPapers).mock.calls[1]![4]!
    expect(retrySignal).not.toBe(firstSignal)
    expect(retrySignal.aborted).toBe(false)
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.error-panel').exists()).toBe(false)

    retry.resolve(response('all'))
    await flushPromises()
    expect(wrapper.get('.paper-card h2').text()).toBe('A preprint')
    expect(wrapper.find('.loader').exists()).toBe(false)
    wrapper.unmount()
  })
})
