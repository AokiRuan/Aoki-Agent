"""配置。全部从环境变量读取，本地用 .env，生产走 App Runner 环境变量。

讲解见 docs/02-project-setup.md。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"

    # 数据库。为空时回退到内存 store，方便本地不起 postgres 也能开发
    database_url: str = ""

    # Langfuse（未配置时静默跳过）
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Agent
    max_iterations: int = 8


settings = Settings()
