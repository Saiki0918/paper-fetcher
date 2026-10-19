# paper-fetcher｜多平台论文搜索系统

一个使用 Vue 3 和 FastAPI 构建的多平台学术论文搜索项目。用户输入关键词后，系统会从多个公开学术信息来源获取结果，将不同格式的数据转换为统一的论文结构，并在同一页面中展示、筛选和跳转至论文详情页或 PDF。


## 项目功能

- 输入中英文关键词搜索论文。
- 支持选择全部平台或单独平台搜索。
- 将各平台返回的不同 JSON/XML 数据统一为 `Paper` 数据结构。
- 展示标题、作者、年份、来源、摘要、DOI、引用量、详情页和 PDF 链接。
- 支持按访问能力筛选：全部、开放获取、有 PDF、仅详情页。
- 多平台搜索时并行请求、去重，并优先展示可公开访问或有 PDF 的论文。
- 后端记录请求、网络、解析和平台错误日志，便于排查问题。

## 界面预览

### 搜索页

![论文搜索页](backend/img/search-view.png)

### 结果页

![论文搜索结果页](backend/img/paper-view.png)

## 已接入的平台

| 平台 | 类型 | 覆盖方向 | 返回格式 | 官网与 API 文档 | 当前说明 |
|---|---|---|---|---|---|
| OpenAlex | 开放学术知识图谱 | 全学科 | JSON | [官网](https://openalex.org/) · [API 文档](https://docs.openalex.org/) | 已实现适配器；当前网络环境可能无法连接 |
| Crossref | DOI 元数据服务 | 全学科正式出版物 | JSON | [官网](https://www.crossref.org/) · [REST API 文档](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | 可用于题目、作者、期刊、DOI 等元数据 |
| arXiv | 开放预印本仓库 | 计算机、数学、物理等 | Atom XML | [官网](https://arxiv.org/) · [API 用户手册](https://info.arxiv.org/help/api/user-manual.html) | 摘要和 PDF 链接较完整 |
| Europe PMC | 生物医学文献平台 | 医学、生命科学 | JSON | [官网](https://europepmc.org/) · [REST Web Service 文档](https://europepmc.org/RestfulWebService) | 可获得部分开放获取与 PDF 信息 |
| PubMed | 生物医学文献索引 | 医学、生命科学 | JSON + XML | [官网](https://pubmed.ncbi.nlm.nih.gov/) · [NCBI E-utilities 详细文档](https://www.ncbi.nlm.nih.gov/books/NBK25500/) | 通过 PMID 检索；有 PMC ID 时通常可访问全文 |
| DBLP | 计算机科学书目库 | 计算机科学 | JSON | [官网](https://dblp.org/) · [API 说明](https://dblp.org/faq/13501473.html) | 适合会议、期刊、作者与 DOI 信息 |
| DOAJ | 开放获取期刊目录 | 全学科 | JSON | [官网](https://doaj.org/) · [v4 API 文档](https://doaj.org/api/v4/docs) | 已实现适配器；当前可能被 Cloudflare 人机验证拦截 |
| bioRxiv | 生命科学预印本 | 生物学、生命科学 | JSON | [官网](https://www.biorxiv.org/) · [Europe PMC API](https://europepmc.org/RestfulWebService) | 通过 Europe PMC 按预印本类型及发布平台检索 |
| medRxiv | 医学预印本 | 临床医学、公共卫生 | JSON | [官网](https://www.medrxiv.org/) · [Europe PMC API](https://europepmc.org/RestfulWebService) | 通过 Europe PMC 按预印本类型及发布平台检索 |
| ChemRxiv | 化学预印本 | 化学及交叉领域 | JSON | [官网](https://chemrxiv.org/) · [Europe PMC API](https://europepmc.org/RestfulWebService) | 当前使用 Europe PMC 收录的记录；不依赖可能返回 403 的原站接口 |
| Research Square | 多学科预印本 | 医学、生命科学等 | JSON | [官网](https://www.researchsquare.com/) · [官方 API 说明](https://www.researchsquare.com/request-api) | 使用官方建议的 Europe PMC 公开索引，无需申请原站令牌 |
| OSF Preprints | OSF 社区预印本合集 | 多学科 | JSON | [官网](https://osf.io/preprints/) · [API 文档](https://developer.osf.io/) | 标题关键词检索，包含各 OSF 社区的公开记录 |
| PsyArXiv | OSF 社区预印本 | 心理学 | JSON | [官网](https://osf.io/preprints/psyarxiv) · [OSF API](https://developer.osf.io/) | 使用 OSF 的 PsyArXiv 社区检索入口 |
| SocArXiv | OSF 社区预印本 | 社会科学 | JSON | [官网](https://osf.io/preprints/socarxiv) · [OSF API](https://developer.osf.io/) | 使用 OSF 的 SocArXiv 社区检索入口 |
| HAL Preprints | 开放仓储中的预印本 / 工作论文 | 多学科 | JSON | [官网](https://hal.science/) · [搜索 API](https://api.archives-ouvertes.fr/docs/search) | 限定 `docType_s:UNDEFINED`，不混入其他文献类别 |
| Zenodo Preprints | 综合仓储中的预印本 | 多学科 | JSON | [官网](https://zenodo.org/) · [API 文档](https://developers.zenodo.org/) | 限定 `type=publication&subtype=preprint`；仅开放 PDF 提供下载链接 |

说明：平台是搜索数据来自哪里；来源（`source`）是论文本身发表的期刊、会议或仓库。例如论文可由 OpenAlex 搜到，但来源是 Nature，详情页位于出版社网站。

新增预印本入口说明：bioRxiv、medRxiv、ChemRxiv、Research Square 的检索服务由 Europe PMC 提供，`platform` 表示用户所选的预印本发布平台，`source` 显示原平台名称，详情链接优先通过 DOI 跳转原文。它们只覆盖 Europe PMC 已收录的记录，可能存在索引延迟，不能视为原平台全库检索。OSF 的当前检索范围为标题，不是摘要或全文；PsyArXiv、SocArXiv 也包含在 OSF 社区合集内。`all` 会对重叠记录去重并保留访问能力更好的记录。

上述四个平台共用索引搜索，并按原平台分别补充 PDF：bioRxiv / medRxiv 查询官方 DOI 明细、核对版本后使用原站入口，Research Square 读取对应版本原文页明确提供的下载链接，ChemRxiv 使用完整 DOI 的原站 PDF 路由。Europe PMC 总入口也对相应 PPR 记录执行同样处理；原站补查失败不影响基础论文返回。具体规则、联网样本结果与 Postman 原站明细示例见 [接口对照说明](docs/postman/README.md)。

SSRN、TechRxiv 暂未接入：尚未确认可稳定用于本项目关键词检索的公开官方 API。

### 各平台 Postman 测试接口

新增预印本来源提供了[可导入的 Postman 集合](docs/postman/preprint-apis.postman_collection.json)与[字段对照说明](docs/postman/README.md)，包含 9 个原始接口、9 个本地接口及 3 个文件 / 元数据排查请求。

以下接口均为关键词 `machine learning`、返回 5 条数据的示例。将整条 URL 复制到 Postman，使用 `GET` 方法发送即可。

| 平台 | 测试接口 |
|---|---|
| OpenAlex | `https://api.openalex.org/works?search=machine%20learning&per-page=5` |
| Crossref | `https://api.crossref.org/works?query.bibliographic=machine%20learning&rows=5` |
| arXiv | `https://export.arxiv.org/api/query?search_query=all:machine_learning&start=0&max_results=5` |
| Europe PMC | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=machine%20learning&format=json&page=1&pageSize=5&resultType=core` |
| PubMed（第一步搜索 PMID） | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=machine%20learning&retmode=json&retmax=5` |
| DBLP | `https://dblp.org/search/publ/api?q=machine%20learning&format=json&h=5` |
| DOAJ | `https://doaj.org/api/search/articles/machine%20learning?page=1&pageSize=5` |
| bioRxiv（Europe PMC 索引） | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=%28machine%20learning%29%20AND%20SRC%3APPR%20AND%20PUBLISHER%3A%22bioRxiv%22&format=json&pageSize=5&resultType=core` |
| medRxiv（Europe PMC 索引） | 同上，将 `bioRxiv` 替换为 `medRxiv` |
| ChemRxiv（Europe PMC 索引） | 同上，将 `bioRxiv` 替换为 `ChemRxiv` |
| Research Square（Europe PMC 索引） | 同上，将 `bioRxiv` 替换为 `Research%20Square` |
| OSF Preprints | `https://api.osf.io/v2/preprints/?filter%5Btitle%5D=machine%20learning&page=1&page%5Bsize%5D=5` |
| PsyArXiv / SocArXiv | `https://api.osf.io/v2/providers/preprints/psyarxiv/preprints/?filter%5Btitle%5D=machine%20learning&page=1&page%5Bsize%5D=5`；SocArXiv 将路径中的 `psyarxiv` 替换为 `socarxiv` |
| HAL Preprints | `https://api.archives-ouvertes.fr/search/?q=machine%20learning&fq=docType_s%3AUNDEFINED&wt=json&start=0&rows=5` |
| Zenodo Preprints | `https://zenodo.org/api/records?q=machine%20learning&type=publication&subtype=preprint&page=1&size=5` |

> PubMed 返回的是 PMID 列表，需要再调用 `efetch.fcgi` 获取论文详细 XML；项目后端已完成这两步请求。DOAJ 在当前网络环境中可能返回 Cloudflare 验证页面，OpenAlex 当前也可能无法连接。

## 技术栈

### 前端

- Vue 3
- TypeScript
- Vue Router
- Vite

### 后端

- Python 3.10 或更高版本
- FastAPI
- Uvicorn
- httpx
- Pydantic Settings

## 目录结构

```text
.
├── backend/                         # FastAPI 后端
│   ├── app/
│   │   ├── api/routes/papers.py     # 统一论文搜索接口
│   │   ├── core/                    # 配置、HTTP 客户端、日志配置
│   │   ├── schemas/paper.py         # Paper 等统一数据模型
│   │   ├── sources/                 # 各学术平台适配器
│   │   └── utils/                   # JSON/XML/文本解析工具
│   └── requirements.txt
├── frontend/
│   └── paper-search/                # Vue 前端项目
│       └── src/
│           ├── services/api.ts      # 调用后端 API
│           ├── types/paper.ts       # 前端论文类型
│           └── views/               # 搜索页和结果页
└── README.md
```

## 本地运行

### 1. 启动后端

先运行 `python --version` 确认当前解释器为 **Python 3.10+**。虚拟环境使用创建它时的 Python 版本；已有 Python 3.8 环境不能通过重新激活升级，需要用新版解释器另建环境。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

如果默认 `python` 版本过旧，可将创建环境的命令替换为 `py -3.12 -m venv .venv`（需已安装并注册 Python 3.12），或使用已安装的新版本 Python 的完整路径执行 `-m venv .venv`。已激活其他虚拟环境时，先运行 `deactivate`，并使用新的目录名保存新环境，避免覆盖旧环境。

后端默认运行在 `http://127.0.0.1:8080`。

可访问 Swagger API 文档：`http://127.0.0.1:8080/docs`

### 2. 启动前端

```powershell
cd frontend\paper-search
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，开发环境通过 Vite 代理将 `/api` 请求转发到后端 `8080` 端口。

## 后端接口示例

```text
GET /api/papers/search?q=machine%20learning&platform=all&page=1&pageSize=10
```

参数：

| 参数 | 说明 |
|---|---|
| `q` | 搜索关键词，必填 |
| `platform` | `all` 或具体平台：`openalex`、`crossref`、`arxiv`、`europepmc`、`pubmed`、`dblp`、`doaj`、`biorxiv`、`medrxiv`、`chemrxiv`、`researchsquare`、`osf`、`psyarxiv`、`socarxiv`、`hal`、`zenodo` |
| `page` | 页码，从 1 开始 |
| `pageSize` | 每页数量，范围为 1–50 |

统一返回中的单篇论文示例：

```json
{
  "id": "arxiv:2306.04338v1",
  "platform": "arxiv",
  "title": "Changing Data Sources in the Age of Machine Learning for Official Statistics",
  "year": 2023,
  "authors": ["Cedric De Boom", "Michael Reusens"],
  "abstract": "...",
  "source": "arXiv · stat.ML",
  "doi": null,
  "url": "https://arxiv.org/abs/2306.04338v1",
  "citationCount": null,
  "isOpenAccess": true,
  "pdfUrl": "https://arxiv.org/pdf/2306.04338v1",
  "accessType": "openPdf"
}
```

## 可选环境变量

项目不创建 `.env` 文件也可以正常启动和调用现有公开 API。只有需要填写联系邮箱、使用某个平台 API Key，或修改端口等配置时，才需要复制 `backend/.env.example` 为 `backend/.env`。

```env
OPENALEX_MAILTO=your_email@example.com
OPENALEX_API_KEY=
CROSSREF_MAILTO=your_email@example.com
NCBI_EMAIL=your_email@example.com
NCBI_API_KEY=
```

- 所有字段都是可选的；保持为空时，项目仍会使用公开接口进行搜索。
- OpenAlex、Crossref 和 PubMed/NCBI 建议在长期或高频使用时填写真实联系邮箱，以符合平台的使用建议。
- `OPENALEX_API_KEY` 与 `NCBI_API_KEY` 仅在你已经申请到对应 Key 时填写，可提高部分平台的请求额度。
- `.env` 可能包含个人配置，已被 Git 忽略，不应提交。

## 日志

后端启动后，日志会同时显示在终端并写入：

```text
backend/logs/paper-search.log
```

日志包含网络请求、超时、HTTP 错误和数据解析问题。日志目录已写入 `.gitignore`，不会被提交。

## 验证

后端适配器和搜索接口的离线回归测试（不访问外网）：

```powershell
cd backend
python -m unittest discover -s tests -v
```

前端测试与构建：

```powershell
cd frontend\paper-search
npm run test:unit -- --run
npm run build
```

实时调用仍受各平台的网络、限流和服务状态影响；失败会通过原有 `meta.failedPlatforms` 或单平台 502 响应呈现。

## 已知限制

- 不同平台的收录范围、相关性排序、总数与引用量统计口径不同。
- 多平台 `all` 搜索的总数是各平台总数相加，属于近似值；同一论文可能被多个平台收录。
- 当前每个平台只请求当前页数据，因此不能实现真正的“全库引用量排序”。
- Crossref、DBLP、PubMed 等平台常没有直接 PDF 或摘要。
- OpenAlex 在当前网络环境下可能无法连接。
- DOAJ 当前可能返回 Cloudflare 人机验证页面，不适合实时服务器端调用。
- 知网、万方、维普等国内大型数据库通常需要机构或商业授权，项目不会绕过登录、验证码或访问限制。

## 后续计划

- 在获得官方授权的前提下接入中文学术平台。
- 优化来源统计与开放全文优先展示策略。
- 为失败平台增加更友好的前端提示与重试策略。
- 如未来需要本地全文检索、收藏、历史记录或全局排序，再引入数据库。
