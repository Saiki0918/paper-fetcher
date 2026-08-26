from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Paper Search API"
    port: int = 8080
    openalex_mailto: str | None = None
    openalex_api_key: str | None = None
    crossref_mailto: str | None = None
    ncbi_email: str | None = None
    ncbi_api_key: str | None = None
    http_timeout_seconds: float = 15.0
    europepmc_timeout_seconds: float = 30.0
    cors_origins_raw: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    # 将逗号分隔的跨域来源配置转换为 FastAPI 可使用的列表。
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


settings = Settings()
