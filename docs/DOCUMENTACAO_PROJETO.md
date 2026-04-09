# Documentação do Projeto — Migração de Metadados CEIE

Documentação de uso do projeto **ceie_proceedings_migration**: pontos de entrada, ferramentas e fluxo de trabalho.  
Não inclui documentação de código (docstrings); foco em **como usar** cada componente.

---

## 1. Visão geral

O projeto extrai e processa metadados de artigos acadêmicos a partir de PDFs e do site OJS (Open Journal System), para migração dos anais do SBIE/WIE (CEIE/SBC) para o servidor SOL da SBC ou site dedicado.

**Fluxo principal (site-first):**

1. Coletar metadados dos artigos no Milanesa/OJS (issue + páginas `rt/metadata`) e **validar o ano** do `config` contra o inferido pelos DOIs (aborta se divergir).  
2. Baixar os PDFs da mesma issue.  
3. Extrair texto dos PDFs **apenas** para contagem de páginas e **referências bibliográficas** (IA nas últimas páginas / seção).  
4. Completar com IA apenas os campos ainda vazios (field completion, mesmo critério de antes).  
5. Gerar CSVs padronizados: Artigos, Autores, Referências, Seções.  

**Estrutura de saída (por ano):**

- `output/{year}/pdfs/` — PDFs baixados  
- `output/{year}/csv/` — Artigos.csv, Autores.csv, Referencias.csv, Secoes.csv  
- `output/{year}/logs/` — JSONs de estado, cache de extração, logs de chamadas à IA  

---

## 2. Pré-requisitos e configuração

### 2.1 Ambiente

- Python 3.x com dependências em `src/requirements.txt`  
- Uso recomendado: ambiente conda `llms` (comandos abaixo com `conda run -n llms` quando aplicável)  
- Variáveis de ambiente carregadas do `.env` na raiz do projeto  

### 2.2 Arquivo `.env`

Criar na raiz do projeto (onde está `src/main.py`):

```
OPENAI_API_KEY=sua_chave_openai
ANTHROPIC_API_KEY=sua_chave_anthropic
```

O provedor de IA é inferido pelo nome do modelo em `config.json` (ex.: `gpt-*` → OpenAI, `claude-*` → Anthropic).

### 2.3 Configuração principal: `config/config.json`

| Chave | Descrição |
|-------|-----------|
| `site_url` | URL da issue/edição OJS (ex.: página do SBIE no Milanesa) |
| `year` | Ano da edição (ex.: `"2018"`) |
| `output_dir` | Diretório base de saída (ex.: `"output/"`) |
| `doi_prefix` | *(Opcional)* Prefixo DOI; se omitido ou `null`, o prefixo é **inferido** a partir dos DOIs extraídos do site |
| `prompts_file` | Caminho do YAML de prompts (ex.: `config/prompts.yaml`) |
| `engine` | Modelo de IA (ex.: `gpt-4o-mini`, `claude-3-5-sonnet`) |
| `max_tokens` | Limite de tokens por resposta |
| `pages_to_process` | Número de páginas por PDF usadas na extração (ex.: 11) |
| `files_to_download` | Quantidade de PDFs a baixar (-1 = todos) |

Outros arquivos em `config/`: `headers.json` (cabeçalhos dos CSVs), `prompts.yaml` (prompts de IA), `section_siglas.json` (siglas de seções).

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
2. Inicializa clientes de IA (LangChain) e o extrator de artigos  
3. Executa o `Migrator`: metadados OJS + validação de ano → download de PDFs → texto dos PDFs (páginas + referências) → inferência de prefixo DOI → field completion → escrita dos CSVs  
4. Gera `output/{year}/csv/Artigos.csv`, `Autores.csv`, `Referencias.csv`, `Secoes.csv` e arquivos em `output/{year}/logs/`  

**Parâmetros de execução:** vêm de `config.json` (`pages_to_process`, `files_to_download`, etc.). Não há argumentos de linha de comando no `main.py`.

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

| Variável | Descrição |
|----------|-----------|
| `dry_run` | `True`: só lista o que seria feito; `False`: altera o CSV |
| `max_articles` | `None` = todos os artigos sem referências; inteiro = limite (ex.: 5 para teste) |
| `year` | `None` = usa o ano de `config.json`; ou ex.: `"2018"` |

**Requisitos:** `config.json` e `.env`; diretório `output/{year}/csv/` com `Artigos.csv` e `Referencias.csv`; PDFs em `output/{year}/pdfs/`.

---

### 4.2 Corretor de e-mails e afiliações — `author_emails_affiliation_corrector.py`

**Objetivo:** Atualizar e-mails e/ou afiliações em `Autores.csv` usando metadados/cache do site e, opcionalmente, extração por IA a partir dos PDFs.

**Uso:**

```bash
conda run -n llms python src/tools/author_emails_affiliation_corrector.py
```

**Configuração:** No bloco `if __name__ == "__main__"`:

| Parâmetro | Descrição |
|-----------|-----------|
| `use_llm_emails` | `False`: só JSON/cache; `True`: extrai e-mails dos PDFs via LLM |
| `use_llm_affiliations` | `True`: usa LLM para recalcular/normalizar afiliações (pt/en) e gera `Autores_afiliacoes_{year}.csv` |
| `max_pages` | Páginas por PDF usadas na extração por LLM (ex.: 1 ou 5) |
| `max_articles` | `None` = todos; inteiro = só os primeiros N (teste) |

**Saída:** `Autores_emails_{year}.csv` (e, se `use_llm_affiliations=True`, `Autores_afiliacoes_{year}.csv`) em `output/{year}/csv/`.

---

### 4.3 Verificação CSV vs Milanesa — `verify_csv_vs_milanesa.py`

**Objetivo:** Comparar título, autores, resumo, idJEMS e pages dos CSVs com os dados atuais do Milanesa (OJS) e gerar relatórios de OK e divergências.

**Uso:**

```bash
conda run -n llms python src/tools/verify_csv_vs_milanesa.py
```

**Configuração:** No `if __name__ == "__main__"`:

| Variável | Descrição |
|----------|-----------|
| `MAX_ARTICLES` | `None` = todos; número = só os N primeiros (ex.: 5 para teste) |
| `YEAR` | `None` = ano do config; ou ex.: `"2018"` |
| `SIMILARITY_THRESHOLD` | Limiar de similaridade para resumos/abstracts (ex.: 0.8) |

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

| Arquivo | Uso como script | Observação |
|---------|----------------------------------|------------|
| `src/utils/pdf_processor.py` | Processa todos os PDFs de um diretório e grava em `outputs/text/` | Diretório hardcoded no exemplo; preferir migração completa |
| `src/services/pdf_downloader.py` | Baixa PDFs de uma URL OJS para um diretório | URL e diretório no `if __name__`; a migração já usa esse serviço |
| `src/services/anais_ojs_html_parser.py` | Extrai informações dos artigos do site e grava em `temp/articles_info.json` | Integrado na migração; uso direto só para debug/inspeção |

---

## 6. Resumo rápido: qual comando usar?

| Objetivo | Comando / Ferramenta |
|----------|----------------------|
| Rodar a migração completa (download + extração + CSVs) | `python src/main.py` |
| Preencher referências que faltam em artigos já migrados | `python -m src.tools.fill_referencias_missing` |
| Atualizar e-mails/afiliações em Autores.csv | `python src/tools/author_emails_affiliation_corrector.py` |
| Comparar CSVs com o Milanesa (batch) | `python src/tools/verify_csv_vs_milanesa.py` |
| Revisar divergências no navegador (Streamlit) | `streamlit run src/tools/streamlit_verificacao_csv_vs_milanesa.py` |
| Conferir referências × PDF no navegador (Streamlit) | `streamlit run src/tools/streamlit_referencias_ultima_pagina.py` |
| Regenerar CSVs a partir dos JSONs de log | `python -m src.tools.regenerate_csv_from_json` |

Sempre executar na **raiz do projeto** e, em ambiente sandbox/CI, usar `conda run -n llms` antes do comando Python/Streamlit.

---

## 7. Convenções do projeto

- **Arquivos temporários:** devem ficar em `temp/` (raiz) ou `src/temp/` conforme regras do projeto.  
- **CSVs:** delimitador `;`, encoding UTF-8; evitar vírgulas dentro de campos.  
- **Backups:** ferramentas que alteram CSVs (ex.: `fill_referencias_missing`) fazem backup em `output/{year}/csv/backups/` antes de modificar.  
- **Idioma:** mensagens ao usuário e interface em português; documentação de código e identificadores em inglês.

---

*Última atualização da documentação: abril de 2026.*
