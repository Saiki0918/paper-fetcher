// 下拉选项、路由校验和显示名称共用同一份平台定义，避免新增来源时遗漏。
export const PAPER_PLATFORMS = [
  { value: 'all', label: '全部平台' },
  { value: 'openalex', label: 'OpenAlex' },
  { value: 'crossref', label: 'Crossref' },
  { value: 'arxiv', label: 'arXiv' },
  { value: 'europepmc', label: 'Europe PMC' },
  { value: 'pubmed', label: 'PubMed' },
  { value: 'dblp', label: 'DBLP' },
  { value: 'doaj', label: 'DOAJ' },
  // 这四项通过 Europe PMC 索引检索；标签明确标注覆盖范围来自索引收录。
  { value: 'biorxiv', label: 'bioRxiv（Europe PMC 索引）' },
  { value: 'medrxiv', label: 'medRxiv（Europe PMC 索引）' },
  { value: 'chemrxiv', label: 'ChemRxiv（Europe PMC 索引）' },
  { value: 'researchsquare', label: 'Research Square（Europe PMC 索引）' },
  // OSF 合集可能与社区专属结果重叠，社区项用于单独限定搜索范围。
  { value: 'osf', label: 'OSF Preprints（社区合集）' },
  { value: 'psyarxiv', label: 'PsyArXiv' },
  { value: 'socarxiv', label: 'SocArXiv' },
  // 综合仓储的后端适配器已限定为预印本或工作论文类别。
  { value: 'hal', label: 'HAL 预印本 / 工作论文' },
  { value: 'zenodo', label: 'Zenodo 预印本' },
] as const

// 从只读配置推导平台标识联合类型，使新增下拉项同步进入请求和响应的类型约束。
export type PaperPlatform = (typeof PAPER_PLATFORMS)[number]['value']

/** 后端统一模型序列化后的 camelCase 字段，各平台缺失的可选信息以 null 表示。 */
export interface Paper {
  id: string
  platform: PaperPlatform
  title: string
  year: number | null
  authors: string[]
  abstract: string | null
  source: string | null
  doi: string | null
  /** 论文详情入口；缺少 PDF 时仍可用于查看原站信息。 */
  url: string
  /** null 表示来源未提供统计，0 表示来源明确返回零引用。 */
  citationCount: number | null
  /** 来源提供的开放或免费访问状态，与是否存在 PDF 链接分别判断。 */
  isOpenAccess: boolean
  /** 来源返回或适配器补充的阅读地址；存在链接不代表已逐篇下载验证。 */
  pdfUrl: string | null
  accessType: PaperAccessType
}

// openPdf：开放且有 PDF；pdf：仅有 PDF 链接；open：仅开放；detail：两者均无。
export type PaperAccessType = 'openPdf' | 'pdf' | 'open' | 'detail'
// 访问筛选作用于已取得的一页结果；开放获取与有 PDF 两类允许重叠。
export type AccessFilter = 'all' | 'openAccess' | 'hasPdf' | 'detailOnly'

export interface PaperSearchMeta {
  query: string
  page: number
  pageSize: number
  /** 上游命中总数，尚未按前端访问方式筛选；跨平台时可能包含重复论文。 */
  total: number
  requestedPlatform: PaperPlatform
  /** 本次成功返回搜索结果的具体平台，all 仅是请求选项。 */
  searchedPlatforms: Exclude<PaperPlatform, 'all'>[]
  /** 跨平台总数是各源命中数之和，不能视为去重后的精确数量。 */
  totalIsApproximate: boolean
  /** 局部失败仅用于提示，其他来源的结果仍放在 data 中。 */
  failedPlatforms: Exclude<PaperPlatform, 'all'>[]
}

export interface ApiError {
  code: string
  message: string
}

export interface PaperSearchResponse {
  data: Paper[]
  meta: PaperSearchMeta
  /** 搜索失败时的统一错误；部分来源失败另由 meta.failedPlatforms 表达。 */
  error: ApiError | null
}
