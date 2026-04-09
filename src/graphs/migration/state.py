from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field


class MigrationState(BaseModel):
    """
    Shared state passed across LangGraph nodes.

    Notes:
    - We avoid storing large PDF page text in the state to keep checkpoints light.
    - Large/expensive artifacts should be saved to disk (output/{year}/logs/).
    """

    # Config / paths
    site_url: str
    output_dir: str
    year: str
    pages_to_process: int = 11
    files_to_download: int = -1
    article_offset: int = 0
    skip_fully_processed_articles: bool = True
    doi_prefix: Optional[str] = None

    pdf_save_dir: str
    csv_save_dir: str
    logs_dir: str

    # Data moving through the pipeline
    website_articles_data_list: list[dict[str, Any]] = Field(default_factory=list)
    sections_data: list[dict[str, Any]] = Field(default_factory=list)

    # Article objects are kept as dicts to keep the state serializable.
    articles_dict_list: list[dict[str, Any]] = Field(default_factory=list)
    updated_articles_dict_list: list[dict[str, Any]] = Field(default_factory=list)

    # Map-reduce: one Send payload per article (enrich PDFs phase)
    enrichment_order: Optional[int] = None
    enrichment_article_dict: Optional[dict[str, Any]] = None
    enriched_article_chunks: Annotated[list[dict[str, Any]], operator.add] = Field(
        default_factory=list
    )
    # Articles already complete in articles_metadata_apos (skip enrich_one_article).
    skipped_enrichment_chunks: list[dict[str, Any]] = Field(default_factory=list)
    # Parallel to articles_dict_list when pending: global index in issue for each pending.
    enrichment_global_orders: Optional[list[int]] = None

    # Map-reduce: one Send payload per article (field completion phase)
    field_completion_order: Optional[int] = None
    field_completion_article_dict: Optional[dict[str, Any]] = None
    field_completion_chunks: Annotated[list[dict[str, Any]], operator.add] = Field(
        default_factory=list
    )

    # Inferred / derived values
    inferred_doi_prefix: Optional[str] = None

    # Errors and execution info
    errors: list[dict[str, Any]] = Field(default_factory=list)
    execution_info: dict[str, Any] = Field(default_factory=dict)

    def ensure_dirs(self) -> None:
        Path(self.pdf_save_dir).mkdir(parents=True, exist_ok=True)
        Path(self.csv_save_dir).mkdir(parents=True, exist_ok=True)
        Path(self.logs_dir).mkdir(parents=True, exist_ok=True)
