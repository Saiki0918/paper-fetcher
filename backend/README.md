# paper-fetcher 后端

这是 `paper-fetcher` 的 FastAPI 后端。它请求公开学术信息来源的 API，并将不同平台返回的 JSON 或 XML 数据转换为统一的 `Paper` 数据结构。具有公开 PDF 或开放获取标记的论文会优先展示。

项目整体说明、平台文档链接和前端启动方法请查看仓库根目录的 [README](../README.md)。

## 启动后端

要求 **Python 3.10+**。先运行 `python --version`；如果显示 3.8，需要使用新版解释器创建新环境，已有虚拟环境不会随系统安装新版 Python 自动升级。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

上面的 `python -m venv .venv` 必须由 Python 3.10+ 执行。也可使用 `py -3.12 -m venv .venv`（需已安装 Python 3.12），或新版 Python 的完整路径。若已激活旧环境，先运行 `deactivate`，并为新环境选择未使用的目录名。

后端启动后，可打开 `http://127.0.0.1:8080/docs` 查看 Swagger 接口文档，或调用：

```text
GET http://localhost:8080/api/papers/search?q=machine%20learning&platform=all&page=1&pageSize=10
```

支持的 `platform` 值为：`all`、`openalex`、`crossref`、`arxiv`、`europepmc`、`pubmed`、`dblp`、`doaj`、`biorxiv`、`medrxiv`、`chemrxiv`、`researchsquare`、`osf`、`psyarxiv`、`socarxiv`、`hal`、`zenodo`。

新增预印本检索不需要额外 API Key。bioRxiv、medRxiv、ChemRxiv、Research Square 通过 Europe PMC 的 `SRC:PPR AND PUBLISHER:...` 过滤实现，只覆盖索引已收录的记录；OSF 及其 PsyArXiv、SocArXiv 社区目前按标题关键词搜索；HAL 和 Zenodo 分别限定预印本 / 工作论文与预印本类别。完整 API 链接与示例见根目录 README。

- `all` 会并行搜索全部平台并去重；总数为近似值。
- 同一论文存在多条记录时，优先保留明确提供 PDF 或开放获取的记录。
- 某个平台暂时不可用时，会在 `meta.failedPlatforms` 中标记，不影响其他平台结果。

`Paper` 通过以下字段描述访问能力：

- `url`：论文详情页或来源页。
- `pdfUrl`：优先解析明确 PDF；两个 Rxiv 站点通过官方 DOI 明细 API 核对版本后补充原站链接，Research Square 从对应版本原文页读取明确下载链接，ChemRxiv 按完整 DOI 补充原站入口并替换失效代理。原站补查最多并发 4 个、整页预算 8 秒，失败时保留论文及详情页；链接可能受原站浏览器验证限制。
- `accessType`：`openPdf`、`pdf`、`open` 或 `detail`，表示这条论文记录的访问能力。

`citationCount` 只使用来源明确提供的被引次数，保留 0；未提供则为 `null`，不以下载量、浏览量或关联正式出版物的引用量代替。OSF 基础检索后会分别补充主文件和作者；补充请求共享 8 秒预算，个别失败不丢弃已返回的论文。用户实测响应的字段差异及 Postman 参数说明见 [对照文档](../docs/postman/README.md)。

## 可选配置

不创建 `backend/.env` 也可以运行。只有需要填写联系邮箱、已有平台 API Key，或修改端口、超时时间时，才复制 `.env.example` 为 `.env` 并填写对应值。

在 VS Code 打开仓库根目录后，选择运行和调试中的 `FastAPI: Paper Search API`，按 `F5` 即可启动。该配置会在 `backend` 目录执行 `app.main`，并在默认的 `8080` 端口启动 Uvicorn。

## 回归测试

在 `backend` 目录执行 `python -m unittest discover -s tests -v`。测试使用固定接口样例和模拟网络响应，验证平台筛选、分页、字段转换、PDF 访问限制、跨平台去重与失败隔离，不依赖外部 API 状态。
