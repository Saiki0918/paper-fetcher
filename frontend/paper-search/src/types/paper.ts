export interface Paper {
  id: string
  platform: PaperPlatform
  title: string
  year: number | null
  authors: string[]
  abstract: string | null
  source: string | null
  doi: string | null
  url: string
  citationCount: number | null
  downloadCount: number | null
  isOpenAccess: boolean
  pdfUrl: string | null
  accessType: PaperAccessType
}

export type PaperPlatform =
  | 'all'
  | 'openalex'
  | 'crossref'
  | 'arxiv'
  | 'europepmc'
  | 'pubmed'
  | 'dblp'
  | 'doaj'

export type PaperAccessType = 'openPdf' | 'pdf' | 'open' | 'detail'
export type AccessFilter = 'all' | 'openAccess' | 'hasPdf' | 'detailOnly'

export interface PaperSearchMeta {
  query: string
  page: number
  pageSize: number
  total: number
  requestedPlatform: PaperPlatform
  searchedPlatforms: Exclude<PaperPlatform, 'all'>[]
  totalIsApproximate: boolean
  failedPlatforms: Exclude<PaperPlatform, 'all'>[]
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
