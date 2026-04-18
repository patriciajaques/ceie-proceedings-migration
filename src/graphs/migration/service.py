from __future__ import annotations

import os
from typing import Any, Optional

from src.config.config_loader import ConfigLoader
from src.services.migrator import Migrator

from .graph import build_migration_graph
from .models import MigrationGraphInput, MigrationGraphOutput
from .state import MigrationState


def _open_sqlite_checkpointer(
    checkpoint_path: str,
) -> tuple[Any, Any]:
    """
    Open SqliteSaver and return (checkpointer, context_manager_or_none).

    Caller must __exit__ the context manager when done if not None.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    cm = SqliteSaver.from_conn_string(checkpoint_path)
    saver = cm.__enter__()
    saver.setup()
    return saver, cm


def _memory_checkpointer() -> Any:
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def _coerce_graph_result(raw: Any) -> MigrationState:
    """
    LangGraph may return a plain dict when compiled without a checkpointer;
    with a checkpointer it often returns the same type as the input state.
    """
    if isinstance(raw, MigrationState):
        return raw
    if isinstance(raw, dict):
        return MigrationState.model_validate(raw)
    raise TypeError(
        f"Unexpected graph invoke result type: {type(raw).__name__!r}; "
        "expected MigrationState or dict."
    )


class MigrationGraphService:
    """
    Service wrapper that runs the central LangGraph pipeline.

    Dependencies are injected via constructor, enabling use from an API layer later.

    When ``persist_checkpoint`` is True (default), the graph is compiled with a
    checkpointer: SQLite at ``{logs_dir}/migration_graph_checkpoint.sqlite`` if
    ``langgraph-checkpoint-sqlite`` is available, otherwise in-memory. Pass the same
    ``thread_id`` on a later run to resume from the last checkpoint.
    """

    def __init__(self, *, config_loader: ConfigLoader, migrator: Migrator):
        self.config_loader = config_loader
        self.migrator = migrator

    def run(self, data: MigrationGraphInput) -> MigrationGraphOutput:
        output_dir = str(self.config_loader.get_config_value("output_dir"))
        year = str(self.config_loader.get_config_value("year"))
        site_url = str(self.config_loader.get_config_value("site_url"))
        doi_prefix = self.config_loader.get_config_value("doi_prefix", None)

        pdf_save_dir = os.path.join(output_dir, f"{year}", "pdfs")
        csv_save_dir = os.path.join(output_dir, f"{year}", "csv")
        logs_dir = os.path.join(output_dir, f"{year}", "logs")

        state = MigrationState(
            site_url=site_url,
            output_dir=output_dir,
            year=year,
            pages_to_process=data.pages_to_process,
            files_to_download=data.files_to_download,
            article_offset=data.article_offset,
            skip_fully_processed_articles=data.skip_fully_processed_articles,
            doi_prefix=doi_prefix,
            pdf_save_dir=pdf_save_dir,
            csv_save_dir=csv_save_dir,
            logs_dir=logs_dir,
        )
        state.ensure_dirs()

        print(
            f"\n>>> Pipeline: ano {year} | PDFs: {pdf_save_dir} | CSV: {csv_save_dir}",
            flush=True,
        )
        if data.max_concurrency == 1:
            print(
                ">>> Concorrência: sequencial (max_concurrency=1).",
                flush=True,
            )
        elif data.max_concurrency is not None:
            print(
                f">>> Concorrência: até {data.max_concurrency} tarefa(s) paralela(s).",
                flush=True,
            )

        thread_id = data.thread_id or f"ceie_migration_{year}"
        checkpoint_path: Optional[str] = None
        checkpoint_backend = "none"
        sqlite_cm: Any = None
        checkpointer: Any | None = None

        if data.persist_checkpoint:
            checkpoint_path = os.path.join(logs_dir, "migration_graph_checkpoint.sqlite")
            try:
                checkpointer, sqlite_cm = _open_sqlite_checkpointer(checkpoint_path)
                checkpoint_backend = "sqlite"
            except ImportError:
                checkpointer = _memory_checkpointer()
                checkpoint_backend = "memory"
                checkpoint_path = None

        invoke_config: dict[str, Any] = {}
        if data.persist_checkpoint and checkpointer is not None:
            invoke_config["configurable"] = {"thread_id": thread_id}
        if data.max_concurrency is not None:
            invoke_config["max_concurrency"] = data.max_concurrency

        try:
            runnable = build_migration_graph(
                migrator=self.migrator, checkpointer=checkpointer
            )
            if invoke_config:
                final_raw = runnable.invoke(state, invoke_config)
            else:
                final_raw = runnable.invoke(state)
            final_state = _coerce_graph_result(final_raw)
        finally:
            if sqlite_cm is not None:
                sqlite_cm.__exit__(None, None, None)

        exec_info = dict(final_state.execution_info or {})
        exec_info.update(
            {
                "checkpoint_backend": checkpoint_backend,
                "checkpoint_path": checkpoint_path,
                "thread_id": thread_id,
                "persist_checkpoint": data.persist_checkpoint,
                "article_offset": data.article_offset,
                "files_to_download": data.files_to_download,
                "skip_fully_processed_articles": data.skip_fully_processed_articles,
                "max_concurrency": data.max_concurrency,
            }
        )

        articles = (
            final_state.updated_articles_dict_list
            or final_state.articles_dict_list
            or []
        )
        return MigrationGraphOutput(
            year=final_state.year,
            csv_dir=final_state.csv_save_dir,
            pdf_dir=final_state.pdf_save_dir,
            articles=articles,
            errors=final_state.errors,
            execution_info=exec_info,
        )
