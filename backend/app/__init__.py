"""后端应用入口的 Python 版本检查。"""

import sys


# 模型使用 int | None 等 Python 3.10+ 类型注解；虚拟环境仍受其 Python 版本限制。
# 在导入模型前提示版本要求，避免旧环境报出难以理解的类型注解异常。
if sys.version_info < (3, 10):
    raise SystemExit(
        "后端需要 Python 3.10 或更高版本；当前为 Python "
        f"{sys.version_info.major}.{sys.version_info.minor}。"
        "请使用新版 Python 创建虚拟环境，再运行 python -m app.main。"
    )
