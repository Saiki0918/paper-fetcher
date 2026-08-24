import type { PaperSearchResponse } from '@/types/paper'

const API_BASE_URL = '/api'

export async function searchPapers(
  query: string,
  page = 1,
  pageSize = 10,
): Promise<PaperSearchResponse> {
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    pageSize: String(pageSize),
  })

  const response = await fetch(`${API_BASE_URL}/papers/search?${params.toString()}`)
  const payload = (await response.json()) as PaperSearchResponse

  if (!response.ok) {
    throw new Error(payload.error?.message ?? '搜索请求失败，请稍后重试')
  }

  return payload
}
