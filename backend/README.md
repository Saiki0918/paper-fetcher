# Paper Search API

FastAPI backend for the Vue paper search frontend. The first adapter calls OpenAlex and returns a normalized `Paper` shape.

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
GET http://localhost:8080/api/papers/search?q=machine%20learning&page=1&pageSize=10
```

When the repository root is open in VS Code, choose `FastAPI: Paper Search API` in
Run and Debug and press F5. The launch configuration runs `app.main` from the
backend directory, where the module starts Uvicorn on port 8080.
