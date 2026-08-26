if __package__ in (None, ""):
    # Make `python app/main.py` work when the file is launched directly.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.papers import router as papers_router
from app.core.config import settings

app = FastAPI(
    title="Paper Search API",
    description="Search academic papers through multiple public scholarly APIs.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers_router)


@app.get("/api/health", tags=["system"])
# 返回服务健康状态，供浏览器或部署环境检查后端是否可用。
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.port,
    )
