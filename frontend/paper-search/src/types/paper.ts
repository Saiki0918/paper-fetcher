export interface Paper {
  id: string
  title: string
  year: number | null
  authors: string[]
  abstract: string | null
  source: string | null
  url: string
  citationCount: number | null
  downloadCount: number | null
  isOpenAccess: boolean
  pdfUrl: string | null
}

export interface PaperSearchMeta {
  query: string
  page: number
  pageSize: number
  total: number
  source: string
}

export interface ApiError {
  code: string
  message: string
}

export interface PaperSearchResponse {
  data: Paper[]
  meta: PaperSearchMeta
  error: ApiError | null
}
