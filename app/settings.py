from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator, model_validator
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
    rag_backend: str = Field(default="keyword")
    chroma_persist_dir: Path = Field(default=PROJECT_ROOT / "data" / "chroma")
    embedding_provider: str = Field(default="remote")
    embedding_model: str = Field(default="text-embedding-v4")
    embedding_dimensions: int = Field(default=1024)
    embedding_enabled: bool = Field(default=True)
    local_embedding_model: str = Field(default="BAAI/bge-base-zh-v1.5")
    local_embedding_dimensions: int = Field(default=768)
    local_embedding_device: str | None = Field(default=None)
    trace_db_url: str | None = Field(default=None)
    trace_db_pool_size: int = Field(default=5)
    trace_db_max_overflow: int = Field(default=10)
    trace_db_connect_timeout: int = Field(default=2)
    local_embedding_query_instruction: str = Field(
        default="为这个句子生成表示以用于检索相关文章："
    )
    rag_top_k: int = Field(default=3)
    rag_score_threshold: float = Field(default=0.45)

    memory_recent_turn_limit: int = Field(default=6, ge=1, le=50)
    memory_summary_enabled: bool = Field(default=True)
    memory_summary_start_turns: int = Field(default=8, ge=2, le=200)
    memory_summary_max_chars: int = Field(default=1200, ge=100, le=8000)
    memory_summary_batch_turns: int = Field(default=3, ge=1, le=50)
    
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    )
    log_level: str = Field(default="INFO")

    @field_validator("flow_dir", "knowledge_dir", "chroma_persist_dir", mode="after")
    @classmethod
    def _resolve_data_paths(cls, v: Path) -> Path:
        """避免 uvicorn 启动目录不在项目根时，相对路径指向错误目录。"""
        if v.is_absolute():
            return v.resolve()
        return (PROJECT_ROOT / v).resolve()

    @model_validator(mode="after")
    def _validate_memory_config(self) -> Settings:
        """校验 memory 摘要配置。"""
        if self.memory_summary_start_turns <= self.memory_recent_turn_limit:
            raise ValueError(
                "memory_summary_start_turns must be greater than memory_recent_turn_limit"
            )
        return self

settings = Settings()
