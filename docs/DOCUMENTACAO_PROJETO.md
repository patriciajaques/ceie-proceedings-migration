# Documentação do Projeto — Migração de Metadados CEIE

Documentação de uso do projeto **ceie_proceedings_migration**: pontos de entrada, ferramentas e fluxo de trabalho.
Não inclui documentação de código (docstrings); foco em **como usar** cada componente.

---

## 1. Visão geral

O projeto extrai e processa metadados de artigos acadêmicos a partir de PDFs e do site OJS (Open Journal System), para migração dos anais do SBIE/WIE (CEIE/SBC) para o servidor SOL da SBC ou site dedicado.

**Fluxo principal (site-first):** a orquestração é um **grafo LangGraph** (`src/graphs/migration/`), com estado compartilhado (`MigrationState`) entre nós. Serviços como `Migrator`, `PDFDownloader` e `ArticleExtractor` são invocados **a partir dos nós** do grafo.

1. Coletar metadados dos artigos no Milanesa/OJS (issue + páginas `rt/metadata`, incluindo **idioma** quando a tabela PKP expõe rótulos como _Language_ / _Idioma_) e **validar o ano** do `config` contra o inferido pelos DOIs (aborta se divergir).
2. Baixar os PDFs da mesma issue (respeitando `files_to_download` e `article_offset`).
3. Opcionalmente **saltar enriquecimento por PDF** para artigos já completos em `articles_metadata_apos_do_field_completion.json` (quando `skip_fully_processed_articles` é `true`).
4. Para cada artigo **do lote**, abrir só o PDF correspondente (`{idJEMS}.pdf`), extrair texto (até `pages_to_process` páginas) para **contagem de páginas** e **referências** (IA); o resultado fica em cache em memória (`_pdf_item_cache`) para reutilizar nas primeiras páginas no field completion — **não** se processam todos os PDFs da pasta de uma vez.
5. Completar com IA apenas os campos ainda vazios (field completion). O **idioma** (`language` em `Artigos.csv`): preferência pelos metadados do site (normalizado para `pt` / `en` / `es`); se continuar em falta, a IA preenche no field completion. **Editoriais (EDT)** seguem regras específicas para `titleEn`/`language` (ver secções 3.2.1 e 3.2.2).
6. Gerar CSVs padronizados: Artigos, Autores, Referências, Seções (e agregação com execuções anteriores quando aplicável). E-mails e afiliações por LLM nos autores são pós-processamento opcional (secção 4.2).

**Estrutura de saída (por ano):**

- `output/{year}/pdfs/` — PDFs baixados
- `output/{year}/csv/` — Artigos.csv, Autores.csv, Referencias.csv, Secoes.csv
- `output/{year}/logs/` — JSONs de estado, cache de referências por artigo (`references_cache.json`), cache da lista de artigos do site (`website_articles_cache.json`), checkpoint opcional do LangGraph (`migration_graph_checkpoint.sqlite`), logs de chamadas à IA

Para **forçar nova raspagem** dos metadados do site (ex.: após mudar regras de siglas no parser), apague `output/{year}/logs/website_articles_cache.json` antes de executar.

---

## 2. Pré-requisitos e configuração

### 2.1 Ambiente

- Python 3.x com dependências em `src/requirements.txt` (inclui **LangChain** para LLMs e **LangGraph** para o grafo da migração central)
- Uso recomendado: ambiente conda com as dependências do projeto (ex.: `llms` ou `ceie`; comandos abaixo usam `conda run -n <env>` quando aplicável)
- Variáveis de ambiente carregadas do `.env` na raiz do projeto

### 2.2 Arquivo `.env`

Criar na raiz do projeto (onde está `src/main.py`):

```
OPENAI_API_KEY=sua_chave_openai
ANTHROPIC_API_KEY=sua_chave_anthropic
```

O provedor de IA é inferido pelo nome do modelo em `config.json` (ex.: `gpt-*` → OpenAI, `claude-*` → Anthropic).

### 2.3 Configuração principal: `config/config.json`

| Chave                           | Descrição                                                                                                                                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `site_url`                      | URL da issue/edição OJS (ex.: página do SBIE no Milanesa)                                                                                                                                                        |
| `year`                          | Ano da edição (ex.: `"2018"`)                                                                                                                                                                                    |
| `output_dir`                    | Diretório base de saída (ex.: `"output/"`)                                                                                                                                                                       |
| `doi_prefix`                    | _(Opcional)_ Prefixo DOI; se omitido ou `null`, o prefixo é **inferido** a partir dos DOIs extraídos do site                                                                                                     |
| `prompts_file`                  | Caminho do YAML de prompts (ex.: `config/prompts.yaml`)                                                                                                                                                          |
| `engine`                        | Modelo de IA (ex.: `gpt-4o-mini`, `claude-3-5-sonnet`)                                                                                                                                                           |
| `max_tokens`                    | Limite de tokens por resposta (GPT-5: inclui raciocínio interno + texto visível)                                                                                                                                 |
| `openai_reasoning_effort`       | Só modelos GPT-5: `minimal` \| `low` \| `medium` \| `high`. Valores maiores tendem a melhorar JSON estruturado, mas gastam mais do orçamento de `max_tokens`. Se a chave faltar no JSON, o código usa `minimal`. |
| `pages_to_process`              | Número máximo de páginas lidas **por PDF** em cada extração (ex.: 11); `-1` = todas                                                                                                                              |
| `files_to_download`             | Quantidade de artigos do lote após `article_offset` (-1 = todos a partir do offset)                                                                                                                              |
| `article_offset`                | Ignora os primeiros N artigos na ordem da edição (para lotes: 0, 10, 20, …)                                                                                                                                      |
| `skip_fully_processed_articles` | Ver nota abaixo (pular enriquecimento por PDF para artigos já completos no JSON `articles_metadata_apos`).                                                                                                       |
| `langchain_tracing`             | Se `false`, define `LANGCHAIN_TRACING_V2=false` (evita erros LangSmith com payloads >25 MB)                                                                                                                      |
| `max_concurrency`               | Limite de paralelismo do LangGraph nos nós com `Send` (`1` = sequencial, menos RAM)                                                                                                                              |

**`skip_fully_processed_articles`:** Depois de montar a lista de artigos a partir do site, o grafo compara cada `idJEMS` com `output/{year}/logs/articles_metadata_apos_do_field_completion.json`. Se existir uma entrada **com metadados de texto considerados completos** (título, resumos, palavras-chave, idioma, etc., conforme `ArticleExtractor.metadata_text_fields_complete`), esse artigo **não** entra no nó que abre o PDF para extrair páginas, referências e correções de DOI — reutiliza-se o dicionário já guardado. No `enrich_merge` volta a juntar-se à ordem da edição com os restantes e o fluxo segue (field completion, CSVs). Com `false`, **todos** os artigos do lote passam pelo enriquecimento por PDF, mesmo repetindo trabalho já feito noutra execução.

Outros arquivos em `config/`: `headers.json` (cabeçalhos dos CSVs), `prompts.yaml` (prompts de IA), `section_siglas.json` (siglas de seções).

**Nota:** Na **primeira** execução sem `website_articles_cache.json`, o parser pode percorrer **toda** a edição no site para preencher o cache; o lote (`files_to_download` / `article_offset`) limita o que segue no grafo.

---

## 3. Ponto de entrada principal: migração completa

### 3.1 Executar a migração

A partir da **raiz do projeto**:

```bash
conda run -n llms python src/main.py
```

Ou, com o ambiente já ativado:

```bash
python src/main.py
```

**O que acontece:**

1. Carrega `.env` e `config/config.json`
2. Inicializa `JsonLogger`, clientes de IA (LangChain), `TextProcessor`, `ArticleExtractor` e `Migrator`
3. Constrói `MigrationGraphService` e executa o grafo LangGraph (`build_migration_graph` → `invoke` com `MigrationState` e config opcional: `thread_id`, `max_concurrency`)
4. Os nós do grafo seguem a ordem em `graph.py` (resumo detalhado de cada nó: `docs/diagrama_chamadas.md`, secção _Sequência de nós — resumo_): metadados OJS → validação de ano → download de PDFs → inferência de prefixo DOI → seções (`Secoes.csv`) → `build_articles` → `skip_completed_articles` → `enrich_prepare` (cache de referências) → **um nó por artigo** `enrich_one_article` (`PDFProcessor.process_pdf_at_path` por ficheiro) → `enrich_merge` → `field_prepare` (`_build_pdf_raw_by_id`, reutilizando cache em memória quando possível) → **um nó por artigo** `field_one_article` → `field_merge` (junta resultados do field completion em `field_completion_merged_dict_list`) → **`author_affiliation_email`** (LLM: afiliação, país por extenso e e-mail a partir da 1ª página do PDF; nomes dos autores inalterados face ao Milanesa) → **`finalize_field_outputs`** (`Migrator.finalize_field_completion_outputs`: merge com `articles_metadata_apos_do_field_completion.json`, `CsvWriter`, `por_workshop/`).
5. Gera `output/{year}/csv/Artigos.csv`, `Autores.csv`, `Referencias.csv`, `Secoes.csv` e arquivos em `output/{year}/logs/`

**Código relacionado:** `src/graphs/migration/` — `state.py` (estado Pydantic, incl. `field_completion_merged_dict_list` entre field completion e gravação final), `nodes.py` (tarefas por nó), `graph.py` (arestas do grafo), `service.py` (`MigrationGraphService`), `models.py` (contratos de entrada/saída do serviço).

**Parâmetros de execução:** vêm de `config.json` (incl. `article_offset`, `skip_fully_processed_articles`, `langchain_tracing`, `max_concurrency`). Não há argumentos de linha de comando no `main.py`.

**Ferramentas em `src/tools/`:** scripts independentes; reutilizam os mesmos serviços onde aplicável (secção 4).

### 3.2 Detalhes do pipeline principal

O comportamento abaixo faz parte do **mesmo** grafo LangGraph executado por `src/main.py` (`ArticleExtractor`, `OJSHTMLParser`, nós `field_one_article`, etc.). Está aqui só como referência; **não** são classes nem scripts separados do fluxo normal.

#### 3.2.1 Field completion — `titleEn` em editoriais (seção EDT)

Para artigos de secção **editorial** (`sectionAbbrev` EDT), o fluxo dedicado `_field_complete_editorial` em `ArticleExtractor` preenche `titleEn` e `language` sem texto do PDF (evita confundir cabeçalhos de página com título).

Títulos em **português só com letras ASCII** (ex.: _Capa dos Anais do 23º SBIE_, _Contra-capa SBIE 2012_) não devem ser tratados como já em inglês só por não terem acentos. O código usa um conjunto de palavras/padrões típicos de português (`_title_likely_portuguese_without_accents` / `_PT_TITLE_TOKENS` em `src/services/article_extractor.py`); nesses casos pede-se tradução à IA em vez de copiar `titleOrig` para `titleEn`.

#### 3.2.2 Idioma — coluna `language` em `Artigos.csv`

Na página `rt/metadata` de cada artigo, o parser (`OJSHTMLParser.get_metadata`) tenta ler a célula ao lado de rótulos como _Language_, _Idioma_, _Submission language_, etc., e normaliza o texto para um código de duas letras **`pt`**, **`en`** ou **`es`** (`_normalize_language_from_metadata`). Artigos **sem** ligação PDF no sumário continuam só com dados do índice e podem ficar sem idioma no HTML.

Se o idioma continuar vazio ou incompleto após essa etapa, o **field completion** (`ArticleExtractor.do_field_completion_of_missing_values_in_dic`) pede à IA o preenchimento junto com os demais campos. No merge da resposta da IA, um idioma **válido vindo do site** prevalece sobre o sugerido pelo modelo.

---

## 4. Ferramentas (tools) — `src/tools/`

Todas devem ser executadas **a partir da raiz do projeto**.

### 4.1 Preencher referências faltantes — `fill_referencias_missing.py`

**Objetivo:** Artigos que não têm linhas em `Referencias.csv` têm referências extraídas do PDF (últimas páginas) pela mesma pipeline da migração; as novas linhas são appendadas em `Referencias.csv` (com backup).

**Uso:**

```bash
conda run -n llms python -m src.tools.fill_referencias_missing
```

**Configuração:** Editar variáveis no `main()` do script:

| Variável       | Descrição                                                                       |
| -------------- | ------------------------------------------------------------------------------- |
| `dry_run`      | `True`: só lista o que seria feito; `False`: altera o CSV                       |
| `max_articles` | `None` = todos os artigos sem referências; inteiro = limite (ex.: 5 para teste) |
| `year`         | `None` = usa o ano de `config.json`; ou ex.: `"2018"`                           |

**Requisitos:** `config.json` e `.env`; diretório `output/{year}/csv/` com `Artigos.csv` e `Referencias.csv`; PDFs em `output/{year}/pdfs/`.

---

### 4.2 Corretor de e-mails e afiliações — `author_emails_affiliation_corrector.py`

**Objetivo:** Atualizar e-mails e/ou afiliações em `Autores.csv` usando metadados/cache do site e, opcionalmente, extração por IA a partir dos PDFs.

**Uso:**

```bash
conda run -n llms python src/tools/author_emails_affiliation_corrector.py
```

**Configuração:** No bloco `if __name__ == "__main__"`:

| Parâmetro              | Descrição                                                                                                             |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `use_llm_emails`       | `False`: só JSON/cache; `True`: extrai e-mails dos PDFs via LLM                                                       |
| `use_llm_affiliations` | `True`: usa LLM para recalcular/normalizar afiliações (pt/en) e gera `Autores_afiliacoes_{year}.csv`                  |
| `max_pages`            | Páginas iniciais de cada PDF enviadas à LLM (e-mails/afiliações); ex.: `1` quando o cabeçalho cabe na primeira página |
| `max_articles`         | `None` = todos; inteiro = só os primeiros N (teste)                                                                   |

**Saída** (tudo em `output/{year}/csv/`):

| Arquivo                         | Quando                                                                                                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Autores.csv`                   | **Sempre** ao final do script: consolida e-mails (JSON/cache ± LLM) e afiliações (se `use_llm_affiliations=True`). Este é o arquivo principal para ferramentas a jusante. |
| `Autores_emails_{year}.csv`     | Sempre: cópia com o mesmo conteúdo consolidado (histórico / inspeção).                                                                                                    |
| `Autores_afiliacoes_{year}.csv` | Se `use_llm_affiliations=True`: cópia focada na passagem de afiliações.                                                                                                   |

**Requisitos para LLM:** `output/{year}/logs/articles_metadata_antes_do_field_completion.json` (ou equivalente com a lista de artigos na ordem da edição) para alinhar `article` no CSV ao `idJEMS` e ao arquivo `{idJEMS}.pdf`. A coluna `article` no CSV é comparada de forma tolerante a tipos (inteiro vs texto).

---

### 4.3 Verificação CSV vs Milanesa — `verify_csv_vs_milanesa.py`

**Objetivo:** Comparar título, autores, resumo, idJEMS e pages dos CSVs com os dados atuais do Milanesa (OJS) e gerar relatórios de OK e divergências.

**Uso:**

```bash
conda run -n llms python src/tools/verify_csv_vs_milanesa.py
```

**Configuração:** No `if __name__ == "__main__"`:

| Variável               | Descrição                                                      |
| ---------------------- | -------------------------------------------------------------- |
| `MAX_ARTICLES`         | `None` = todos; número = só os N primeiros (ex.: 5 para teste) |
| `YEAR`                 | `None` = ano do config; ou ex.: `"2018"`                       |
| `SIMILARITY_THRESHOLD` | Limiar de similaridade para resumos/abstracts (ex.: 0.8)       |

**Saída em `temp/`:**

- `verificacao_csv_vs_milanesa_OK_YYYYMMDD_HHMMSS.csv` — itens consistentes
- `verificacao_csv_vs_milanesa_DIVERGE_YYYYMMDD_HHMMSS.csv` — divergências ou ausentes no Milanesa

Resumo (contagens e divergências por campo) é impresso no terminal.

---

### 4.4 Regenerar CSVs a partir dos JSONs — `regenerate_csv_from_json.py`

**Objetivo:** Regenerar Artigos.csv, Autores.csv e Referencias.csv a partir dos JSONs de log da migração, sem rodar a pipeline de extração de novo. Útil após execução interrompida ou para inspecionar o estado atual dos metadados.

**Uso:**

```bash
conda run -n llms python -m src.tools.regenerate_csv_from_json
```

**Comportamento:**

- Lê primeiro `articles_metadata_apos_do_field_completion.json` em `output/{year}/logs/`
- Se não existir, usa `articles_metadata_antes_do_field_completion.json`
- Regenera os três CSVs em `output/{year}/csv/` com o `CsvWriter` padrão

**Requisitos:** Pelo menos um dos dois JSONs em `output/{year}/logs/`; `config.json` com `output_dir` e `year` corretos.

---

### 4.5 App Streamlit: Verificação CSV vs Milanesa — `streamlit_verificacao_csv_vs_milanesa.py`

**Objetivo:** Interface web para revisar artigos com divergências: lista de artigos, campos divergentes e visualização da primeira página do PDF (com opção de cortar o topo).

**Uso:**

```bash
conda run -n llms streamlit run src/tools/streamlit_verificacao_csv_vs_milanesa.py
```

**Requisitos:** Ter rodado antes `verify_csv_vs_milanesa.py` para gerar em `temp/` um arquivo `verificacao_csv_vs_milanesa_DIVERGE_*.csv`. O app usa o mais recente. CSVs em `output/{year}/csv/` e PDFs em `output/{year}/pdfs/`.

---

### 4.6 App Streamlit: Referências × última página do PDF — `streamlit_referencias_ultima_pagina.py`

**Objetivo:** Visualizar, por artigo, as referências do `Referencias.csv` (esquerda) e as últimas páginas do PDF (direita) para conferência manual.

**Uso:**

```bash
conda run -n llms streamlit run src/tools/streamlit_referencias_ultima_pagina.py
```

**Requisitos:** `output/{year}/csv/Artigos.csv`, `Referencias.csv` e `output/{year}/pdfs/` com os PDFs. Ano e diretórios vêm de `config.json`.

---

## 5. Módulos executáveis como `__main__` (uso avançado)

Estes são pontos de entrada secundários, em geral para teste ou uso interno; a documentação de uso recomendado está acima.

| Arquivo                                 | Uso como script                                                                       | Observação                                                                                                |
| --------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `src/utils/pdf_processor.py`            | Biblioteca: `extract_text_from_each_page`, `process_pdf_at_path` (um PDF por caminho) | Usado pelo grafo e pelo `Migrator`; não há mais `process_all_pdfs` nem script `__main__` de pasta inteira |
| `src/services/pdf_downloader.py`        | Baixa PDFs de uma URL OJS para um diretório                                           | URL e diretório no `if __name__`; a migração já usa esse serviço                                          |
| `src/services/anais_ojs_html_parser.py` | Extrai informações dos artigos do site e grava em `temp/articles_info.json`           | Integrado na migração; uso direto só para debug/inspeção                                                  |

---

## 6. Resumo rápido: qual comando usar?

| Objetivo                                                | Comando / Ferramenta                                               |
| ------------------------------------------------------- | ------------------------------------------------------------------ |
| Rodar a migração completa (download + extração + CSVs)  | `python src/main.py`                                               |
| Preencher referências que faltam em artigos já migrados | `python -m src.tools.fill_referencias_missing`                     |
| Atualizar e-mails/afiliações em Autores.csv             | `python src/tools/author_emails_affiliation_corrector.py`          |
| Comparar CSVs com o Milanesa (batch)                    | `python src/tools/verify_csv_vs_milanesa.py`                       |
| Revisar divergências no navegador (Streamlit)           | `streamlit run src/tools/streamlit_verificacao_csv_vs_milanesa.py` |
| Conferir referências × PDF no navegador (Streamlit)     | `streamlit run src/tools/streamlit_referencias_ultima_pagina.py`   |
| Regenerar CSVs a partir dos JSONs de log                | `python -m src.tools.regenerate_csv_from_json`                     |

Sempre executar na **raiz do projeto** e, em ambiente sandbox/CI, usar `conda run -n llms` antes do comando Python/Streamlit.

---

## 7. Convenções do projeto

- **Orquestração central:** LangGraph em `src/graphs/migration/`; chamadas à IA continuam via LangChain (`LangChainClient`).
- **Arquivos temporários:** devem ficar em `temp/` (raiz) ou `src/temp/` conforme regras do projeto.
- **CSVs:** delimitador `;`, encoding UTF-8; evitar vírgulas dentro de campos.
- **Backups:** ferramentas que alteram CSVs (ex.: `fill_referencias_missing`) fazem backup em `output/{year}/csv/backups/` antes de modificar.
- **Idioma:** mensagens ao usuário e interface em português; documentação de código e identificadores em inglês.

---

_Última atualização da documentação: abril de 2026._
