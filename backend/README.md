# paper-fetcher 后端

这是 `paper-fetcher` 的 FastAPI 后端。它请求公开学术信息来源的 API，并将不同平台返回的 JSON 或 XML 数据转换为统一的 `Paper` 数据结构。具有公开 PDF 或开放获取标记的论文会优先展示。

项目整体说明、平台文档链接和前端启动方法请查看仓库根目录的 [README](../README.md)。

## 启动后端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

后端启动后，可打开 `http://127.0.0.1:8080/docs` 查看 Swagger 接口文档，或调用：

```text
GET http://localhost:8080/api/papers/search?q=machine%20learning&platform=all&page=1&pageSize=10
```

支持的 `platform` 值为：`all`、`openalex`、`crossref`、`arxiv`、`europepmc`、`pubmed`、`dblp`、`doaj`。

- `all` 会并行搜索全部平台并去重；总数为近似值。
- 某个平台暂时不可用时，会在 `meta.failedPlatforms` 中标记，不影响其他平台结果。

`Paper` 通过以下字段描述访问能力：

- `url`：论文详情页或来源页。
- `pdfUrl`：平台已提供的直接 PDF 地址。
- `accessType`：`openPdf`、`pdf`、`open` 或 `detail`，表示这条论文记录的访问能力。

## 可选配置

不创建 `backend/.env` 也可以运行。只有需要填写联系邮箱、已有平台 API Key，或修改端口、超时时间时，才复制 `.env.example` 为 `.env` 并填写对应值。

在 VS Code 打开仓库根目录后，选择运行和调试中的 `FastAPI: Paper Search API`，按 `F5` 即可启动。该配置会在 `backend` 目录执行 `app.main`，并在默认的 `8080` 端口启动 Uvicorn。
