from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_FLOW_DIR = PROJECT_ROOT / "data" / "flows"
DEFAULT_KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="customer_hand")
    app_version: str = Field(default="0.1.0")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    llm_enabled: bool = Field(default=False)
    flow_dir: Path = Field(default=DEFAULT_FLOW_DIR)
    knowledge_dir: Path = Field(default=DEFAULT_KNOWLEDGE_DIR)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    )
    log_level: str = Field(default="INFO")

    @field_validator("flow_dir", "knowledge_dir", mode="after")
    @classmethod
    def _resolve_data_paths(cls, v: Path) -> Path:
        """避免 uvicorn 启动目录不在项目根时，相对路径指向错误目录。"""
        if v.is_absolute():
            return v.resolve()
        return (PROJECT_ROOT / v).resolve()


settings = Settings()
