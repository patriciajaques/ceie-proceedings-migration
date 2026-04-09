# Diagrama de chamadas – CEIE Proceedings Migration

O projeto **não usa LangGraph**. Usa **LangChain** (ChatOpenAI, ChatAnthropic, etc.) apenas para abstrair chamadas a LLMs (OpenAI, Anthropic, etc.).

Fluxo resumido: `main` → carrega config e clientes de IA → cria `Migrator` → `migrate()` busca metadados no Milanesa/OJS, **valida o ano** (DOIs), baixa PDFs, extrai texto dos PDFs só para **páginas + referências**, completa campos faltantes com IA (B2) e grava CSVs.

---

## Diagrama de sequência (chamadas principais)

Cada caixa é um método/função; setas indicam “quem chama quem”.

```mermaid
sequenceDiagram
    participant main as main()
    participant ConfigLoader
    participant JsonLogger
    participant LangChainClient
    participant TextProcessor
    participant ArticleExtractor
    participant Migrator
    participant PDFDownloader
    participant PDFProcessor
    participant OJSHTMLParser
    participant CsvWriter

    main->>ConfigLoader: __init__(filepath)
    ConfigLoader->>ConfigLoader: load_configuration()
    main->>JsonLogger: initialize(config_loader)
    main->>LangChainClient: __init__(x5 clientes)
    LangChainClient->>LangChainClient: _detect_provider(), get_credentials_manager(), initialize_client()
    main->>TextProcessor: __init__(ai_client)
    main->>ArticleExtractor: __init__(ai_clients, text_processor, ...)
    main->>Migrator: __init__(config_loader, article_extractor)
    main->>Migrator: migrate(pages_to_process, files_to_download)

    Migrator->>Migrator: _get_website_articles_data(num_files)
    Migrator->>Migrator: _validate_year_matches_site_or_abort(website_articles_data_list)

    Migrator->>PDFDownloader: donwload_pdf_files_from_url(num_files)
    PDFDownloader->>PDFDownloader: get_pdf_urls()
    loop por cada PDF
        PDFDownloader->>PDFDownloader: download_and_save_pdf(url)
    end

    Migrator->>Migrator: extract_metadata(num_files, num_pages, website_articles_data_list)
    Migrator->>PDFProcessor: process_all_pdfs(save_files, number_of_pages_to_process)
    loop por cada PDF
        PDFProcessor->>PDFProcessor: extract_text_from_each_page(pdf_path)
    end

    Note over Migrator: Metadados do site já foram obtidos antes do download; aqui reutiliza a lista passada.

    Migrator->>Migrator: _infer_doi_prefix (a partir dos DOIs do site)
    Migrator->>OJSHTMLParser: extract_sections_from_website()
    Migrator->>CsvWriter: write_sections_csv(csv_save_dir, sections_data)

    loop por cada artigo (site como fonte principal)
        Migrator->>Migrator: Article.from_dict(website_article)
    end

    loop por artigo com PDF correspondente (idJEMS = base_filename)
        Migrator->>Migrator: update_pages(first_page, num_pages)
        Migrator->>ArticleExtractor: get_reference_pages_text(pdf_item, section|last)
        Migrator->>ArticleExtractor: extract_references_metadata_with_ai(texto)
        Migrator->>Migrator: correct_doi(article)
    end

    Migrator->>JsonLogger: print_json("articles_metadata_antes_do_field_completion", ...)

    Migrator->>Migrator: complete_missing_fields(articles_list)
    Migrator->>Migrator: _load_completion_cache()
    Migrator->>JsonLogger: read_json_file("articles_metadata_apos_do_field_completion.json")
    Migrator->>ArticleExtractor: do_field_completion_of_missing_values_in_dic(articles_list, completion_cache)
    Migrator->>JsonLogger: print_json("articles_metadata_apos_do_field_completion", ...)
    Migrator->>CsvWriter: __init__(); write_dicts_to_csv(updated_articles)
    Migrator->>Migrator: write_csv_by_workshop(updated_articles)
```

---

## ArticleExtractor – uso na migração principal vs. legado

Na migração atual, o `Migrator` **não** chama `extract_articles_data_from_PDF_text` nem `extract_article_data`. Esses métodos permanecem no código para experimentos ou ferramentas futuras; o fluxo principal usa apenas:

- `get_reference_pages_text` + `extract_references_metadata_with_ai` (referências a partir do PDF)
- `extract_pages` (field completion quando o resumo está vazio e precisa de texto das primeiras páginas)
- `do_field_completion_of_missing_values_in_dic` (campos faltantes, B2)

```mermaid
flowchart TB
    subgraph migrator_hoje["Migrator (site-first)"]
        M1[Article.from_dict dados OJS] --> M2[PDF: num_pages, pages]
        M2 --> M3[get_reference_pages_text]
        M3 --> M4[extract_references_metadata_with_ai]
        M4 --> M5[correct_doi]
        M5 --> M6[do_field_completion ...]
    end

    subgraph legado["Não usado pelo main.py"]
        L1[extract_articles_data_from_PDF_text] --> L2[extract_article_data]
        L2 --> L3[extract_metadata_with_ai título/resumo/refs do PDF]
    end
```

### Detalhe legado: `extract_articles_data_from_PDF_text` (opcional)

```mermaid
flowchart TB
    subgraph extract_articles_data_from_PDF_text
        A1[_load_extraction_cache] --> A2{para cada PDF}
        A2 --> A3{cache tem base_filename?}
        A3 -->|sim| A4[Article.from_dict do cache]
        A3 -->|não| A5[extract_article_data]
        A5 --> A6[_save_extraction_cache]
    end

    subgraph extract_article_data
        B1[extract_pages first] --> B2[text_processor.clean_text]
        B2 --> B3[extract_pages last / section]
        B3 --> B4[extract_metadata_with_ai]
        B4 --> B5[Article.from_dict]
    end
```

### `extract_metadata_with_ai` (dentro de `extract_article_data`)

```mermaid
flowchart TB
    subgraph extract_metadata_with_ai
        C1[extract_article_metadata_with_ai] --> C2[extract_info_with_ai article_ai_client]
        C2 --> C3{sectionAbbrev != EDT?}
        C3 -->|sim| C4[extract_references_metadata_with_ai]
        C4 --> C5[extract_info_with_ai references_ai_client]
        C3 -->|não| C6[references = []]
    end
```

### `extract_info_with_ai`

```mermaid
flowchart TB
    subgraph extract_info_with_ai
        D1[ai_client.create_completion] --> D2[_log_ai_call]
        D2 --> D3[parse_ai_response]
        D3 --> D4{JSON ok?}
        D4 -->|não, tentativas < 3| D1
        D4 -->|sim ou falha| D5[retorna dict]
    end
```

### TextProcessor.clean_text

```mermaid
flowchart TB
    subgraph TextProcessor.clean_text
        E1[detect_encoding_errors]
        E1 --> E2{erros?}
        E2 -->|sim| E3[process_with_ai -> ai_client.create_completion]
        E2 -->|não| E4[basic_cleaning]
    end
```

---

## do_field_completion (ArticleExtractor)

```mermaid
flowchart LR
    A[do_field_completion_of_missing_values_in_dic] --> B{para cada article}
    B --> C{id_jems no completion_cache e sem campos vazios?}
    C -->|sim| D[Article.from_dict cache]
    C -->|não| E{tem título e não EDT e has_empty_fields?}
    E -->|sim| F[extract_info_with_ai field_completion_ai_client]
    F --> G[Article.from_dict new_dict]
    E -->|não| H[mantém article]
```

---

## Migrator: enriquecimento site-first (substitui merge antigo)

O merge antigo (`merge_article_info` + PDF como fonte principal de metadados) foi removido. O fluxo equivalente hoje:

```mermaid
flowchart TB
    S[website_articles_data_list do OJS] --> S1[Article.from_dict por artigo]
    S1 --> S2{PDF existe para idJEMS?}
    S2 -->|sim| S3[update_pages + referências do PDF]
    S2 -->|não| S4[só correct_doi]
    S3 --> S5[correct_doi]
    S4 --> S5
```

`_infer_doi_prefix` roda a partir dos DOIs já presentes na lista do site (antes do loop de enriquecimento por PDF).

---

## CsvWriter.write_dicts_to_csv

```mermaid
flowchart TB
    W[write_dicts_to_csv] --> W1[write_to_csv path_artigos, process_artigos_data]
    W --> W2[write_to_csv path_autores, process_autores_data]
    W --> W3[write_to_csv path_references, process_references_data]
    W1 --> P[write_to_csv: load_headers, DictWriter, para cada item process_function]
    W2 --> P
    W3 --> P
    P --> PA[process_artigos_data -> process_data]
    P --> PB[process_autores_data -> process_items_data authors]
    P --> PC[process_references_data -> process_items_data references]
    PB --> PD[process_data por autor]
    PC --> PE[process_data por referência]
```

---

## Resumo por módulo

| Módulo            | Métodos chamados (principais) |
|-------------------|-------------------------------|
| **main**          | ConfigLoader, JsonLogger.initialize, LangChainClient(x5), TextProcessor, ArticleExtractor, Migrator, migrate() |
| **Migrator**      | _get_website_articles_data, _validate_year_matches_site_or_abort, downloader.donwload_pdf_files_from_url, extract_metadata, _extract_references_from_pdf_item, complete_missing_fields, _load_completion_cache, write_csv_by_workshop, update_pages, correct_doi, _normalize_doi, _infer_doi_prefix |
| **PDFDownloader** | get_pdf_urls, download_and_save_pdf (requests.get) |
| **PDFProcessor**  | process_all_pdfs, extract_text_from_each_page (fitz) |
| **OJSHTMLParser** | extract_articles_info_from_the_website, download_html_and_create_parser, extract_sections_from_website, get_metadata, convert_url, _generate_section_abbrev, _make_abbrev_unique |
| **ArticleExtractor** | get_reference_pages_text, extract_references_metadata_with_ai, extract_pages, extract_info_with_ai, do_field_completion_of_missing_values_in_dic, has_empty_fields, parse_ai_response, _log_ai_call; *legado/não usado pelo main:* extract_articles_data_from_PDF_text, extract_article_data, extract_metadata_with_ai |
| **TextProcessor** | clean_text, detect_encoding_errors, basic_cleaning, process_with_ai |
| **LangChainClient** | _detect_provider, get_credentials_manager, initialize_client (ChatOpenAI/ChatAnthropic), create_completion (invoke messages) |
| **BaseAIClient**  | load_prompt (ConfigLoader), get_credentials().get("api_key"), initialize_client() |
| **ConfigLoader**  | load_configuration, get_config_value, load_prompt |
| **JsonLogger**    | initialize, get_base_dir, _prepare_path, print_json, read_json_file |
| **CsvWriter**     | load_headers, write_to_csv, write_dicts_to_csv, process_artigos_data, process_autores_data, process_references_data, process_data, process_items_data, write_sections_csv |

---

## Observação

**LangGraph** não é usado. O fluxo é procedural: `main` → `Migrator.migrate()` → metadados OJS + validação de ano → download → texto PDF só para páginas/referências → field completion com IA → escrita em CSV. A IA é usada via **LangChain** (ChatOpenAI, ChatAnthropic, etc.) dentro de `LangChainClient.create_completion()`.
