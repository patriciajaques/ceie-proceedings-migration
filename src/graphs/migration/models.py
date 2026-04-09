from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class MigrationGraphInput(BaseModel):
    """
    Input contract for the central migration graph.

    This is intentionally minimal because the project uses config/config.json as
    the primary configuration source.
    """

    pages_to_process: int = Field(default=11, ge=1)
    files_to_download: int = Field(default=-1)
    article_offset: int = Field(
        default=0,
        ge=0,
        description=(
            "Skip first N articles in issue order. Use with files_to_download as batch "
            "size (e.g. offset=0 count=10, then offset=10 count=10)."
        ),
    )
    skip_fully_processed_articles: bool = Field(
        default=True,
        description=(
            "If True, skip PDF enrichment for articles already fully present in "
            "articles_metadata_apos_do_field_completion.json (has_empty_fields false)."
        ),
    )
    persist_checkpoint: bool = Field(
        default=True,
        description="If True, compile with a checkpointer (SQLite under logs/ or memory).",
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="LangGraph thread_id for resume; defaults to ceie_migration_{year}.",
    )
    max_concurrency: Optional[int] = Field(
        default=None,
        description=(
            "LangGraph RunnableConfig max_concurrency (thread pool for parallel Send "
            "branches). Set 1 to run enrich_one_article / field_one_article one at a "
            "time (lower RAM). None omits the key (default parallel behaviour)."
        ),
    )

    @field_validator("max_concurrency")
    @classmethod
    def _max_concurrency_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("max_concurrency must be >= 1 when set")
        return v


class MigrationGraphOutput(BaseModel):
    """
    Output contract for the central migration graph.

    The `articles` list contains dicts in the same shape produced by Article.to_dict().
    """

    year: str
    csv_dir: str
    pdf_dir: str
    articles: list[dict[str, Any]]
    errors: list[dict[str, Any]] = Field(default_factory=list)
    execution_info: dict[str, Any] = Field(default_factory=dict)
