import type { PaperPlatform, PaperSearchResponse } from '@/types/paper'

const API_BASE_URL = '/api'

// 请求后端论文搜索接口，并将响应解析为统一的搜索结果类型。
export async function searchPapers(
  query: string,
  platform: PaperPlatform = 'all',
  page = 1,
  pageSize = 10,
  signal?: AbortSignal,
): Promise<PaperSearchResponse> {
  const params = new URLSearchParams({
    q: query,
    platform,
    page: String(page),
    pageSize: String(pageSize),
  })

  // 将页面的取消信号传给 fetch，使取消能中止网络等待或尚未结束的响应体读取。
  const response = await fetch(`${API_BASE_URL}/papers/search?${params.toString()}`, { signal })
  const payload = (await response.json()) as PaperSearchResponse

  if (!response.ok) {
    throw new Error(payload.error?.message ?? '搜索请求失败，请稍后重试')
  }

  return payload
}
