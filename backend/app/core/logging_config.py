"""集中配置项目日志的输出格式、级别和日志文件轮换规则。"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DIRECTORY = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIRECTORY / "paper-search.log"


# 配置根日志器，使全部模块的日志同时输出到终端和滚动日志文件。
def configure_logging() -> None:
    """Configure application logging once; safe to call again after a reload."""
    root_logger = logging.getLogger()
    if getattr(root_logger, "_paper_search_configured", False):
        return

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 单个文件最多 2 MB，保留最近 5 个旧文件，防止日志无限占用硬盘。
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger._paper_search_configured = True  # type: ignore[attr-defined]

