import { afterEach, expect, it, vi } from 'vitest'
import { searchPapers } from '@/services/api'
import type { PaperSearchResponse } from '@/types/paper'

afterEach(() => {
  // fetch 是全局网络边界，用例结束后恢复，避免影响其他组件或请求测试。
  vi.unstubAllGlobals()
})

// 页面传入信号还不够，请求层必须把同一个信号继续交给实际执行网络请求的 fetch。
it('passes the cancellation signal to fetch and preserves the response', async () => {
  const payload: PaperSearchResponse = {
    data: [],
    meta: {
      query: 'machine learning',
      page: 2,
      pageSize: 10,
      total: 0,
      requestedPlatform: 'biorxiv',
      searchedPlatforms: ['biorxiv'],
      totalIsApproximate: false,
      failedPlatforms: [],
    },
    error: null,
  }
  const fetchMock = vi
    .fn<typeof fetch>()
    .mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  const controller = new AbortController()

  const result = await searchPapers('machine learning', 'biorxiv', 2, 10, controller.signal)

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/papers/search?q=machine+learning&platform=biorxiv&page=2&pageSize=10',
    { signal: controller.signal },
  )
  expect(result).toEqual(payload)
})
