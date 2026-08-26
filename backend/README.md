# Paper Search API

FastAPI backend for the Vue paper search frontend. It queries public scholarly APIs
and returns a normalized `Paper` shape. Records with public full-text PDFs are
ranked before records that only expose a landing page.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
```

Then open `http://localhost:8080/docs` or call:

```text
GET http://localhost:8080/api/papers/search?q=machine%20learning&platform=all&page=1&pageSize=10
```

Supported `platform` values are `all`, `openalex`, `crossref`, `arxiv`, `europepmc`,
`pubmed`, `dblp`, and `doaj`. `all` searches them in parallel and returns
de-duplicated results; its total is approximate. A platform that is temporarily
unavailable is listed in `meta.failedPlatforms` without failing the other results.

`Paper` has three fields for access capability:

- `url`: the source's landing/detail page.
- `pdfUrl`: a known direct PDF URL, when provided by the platform.
- `accessType`: `openPdf`, `pdf`, `open`, or `detail`. This is a record-level
  capability and does not claim that every article from the same publication source
  is accessible.

For PubMed, set `NCBI_EMAIL` to a real contact address in `.env`; `NCBI_API_KEY`
is optional and increases its request allowance.

When the repository root is open in VS Code, choose `FastAPI: Paper Search API` in
Run and Debug and press F5. The launch configuration runs `app.main` from the
backend directory, where the module starts Uvicorn on port 8080.
