# Onde os dados são salvos e o que acontece se o programa abortar

Este documento descreve onde as informações processadas dos artigos são persistidas e o comportamento em caso de interrupção da execução (aborto, Ctrl+C, falha de rede, etc.). Útil para planejar um grafo LangGraph que processe **um artigo por vez** e persista por artigo.

## Visão geral do fluxo atual

O fluxo é em **lote** por fase:

1. **Download dos PDFs** → disco
2. **Dados do site** → cache único
3. **Processamento de todos os PDFs** (texto) → em memória
4. **Extração de metadados** (por artigo, com cache incremental)
5. **Merge** site + PDF → em memória
6. **Field completion** (por artigo, mas escrita só no fim)
7. **Escrita dos CSVs** → uma vez no fim

---

## Ordem das chamadas à LLM (LangSmith)

Não é “primeiro todas as correções de texto, depois todos os dicionários”. A ordem é a seguinte.

### Fase 1 — Extração (dentro de `extract_articles_data_from_PDF_text`)

Para **cada** artigo (não está no cache):

1. `clean_text(primeiras páginas)` → se houver erros de encoding, **1 chamada `text_processing`**
2. `clean_text(últimas páginas)` → se houver erros de encoding, **mais 1 chamada `text_processing`**
3. `extract_metadata_with_ai(...)` → **1 chamada `article_extraction`** (aqui a LLM gera o dicionário JSON do artigo a partir do texto do PDF)

Ou seja: por artigo você vê algo como `[text_processing?, text_processing?, article_extraction]`. A geração do dicionário (**article_extraction**) acontece **logo após** as correções de texto daquele mesmo artigo.

Se o artigo já estiver no **extraction_cache**, esse bloco inteiro é pulado (nenhuma chamada à LLM para esse artigo).

### Fase 2 — Field completion (dentro de `complete_missing_fields`)

O programa **não** limpa o texto de todos os PDFs de uma vez. Ele mantém só o texto **bruto** por artigo (`_build_pdf_raw_by_id()`: sem `clean_text`). Para **cada** artigo que vai passar pelo field completion e precisa do texto do PDF (resumo vazio):

1. Chama `clean_text(primeiras páginas)` **só para esse artigo** → 1 chamada `text_processing` (se houver erros de encoding)
2. Em seguida chama a LLM para **`field_completion`** com o texto corrigido

Ou seja: o padrão é o mesmo da fase 1 — **correção de texto apenas do artigo que está sendo processado**, logo antes de gerar/completar o dicionário. Não há mais um bloco de N chamadas `text_processing` para todos os artigos.

Resumo no LangSmith:

- **`text_processing`**: correção de encoding (na extração ou em `_build_pdf_text_by_id`).
- **`article_extraction`**: geração do dicionário JSON a partir do PDF (só na fase de extração; se todos os artigos vierem do cache, não aparece).
- **`field_completion`**: completar resumo, palavras-chave etc. quando o artigo precisa do texto do PDF, antes disso é feita uma chamada `text_processing` só para esse artigo.

As chamadas para gerar ou completar o dicionário são **`article_extraction`** (fase 1) e **`field_completion`** (fase 2). As chamadas para “gerar/completar o dicionário” são **`article_extraction`** (fase 1) e **`field_completion`** (fase 2); vale filtrar ou rolar o LangSmith por esses nomes de etapa.

---

## Texto do PDF após extração e correção: é salvo?

**Não.** O conteúdo do PDF **apenas corrigido** pela LLM (etapa `text_processing` — correção de encoding) **não é persistido em nenhum arquivo**.

 - Esse texto corrigido existe **só em memória** durante a execução.
- Ele é usado na sequência para: (1) extração de metadados do artigo (que gera o dicionário JSON) e/ou (2) field completion quando falta resumo. O que é salvo é o **resultado** (os dicionários JSON), não o texto corrigido em si.
- Se a execução abortar no meio, esse texto corrigido é perdido. Na próxima execução, o mesmo PDF será enviado de novo à LLM para correção de encoding (e nova chamada `text_processing`), se ainda for processado.
 
Além disso, **a extração de texto do PDF passou a ter duas camadas antes da LLM**:

- Primeira camada: extração com **PyMuPDF** usando `TextPage` e flags de texto, que melhora o mapeamento de glifos para Unicode em muitos PDFs.
- Segunda camada: um **validador simples de qualidade de texto** (baseado em padrões de encoding quebrado) decide se o texto parece suspeito.
  - Se o texto extraído por PyMuPDF for considerado suspeito, o sistema tenta um **fallback com `pdftotext` (Poppler)** para o mesmo PDF.
  - Se o texto vindo de `pdftotext` parecer melhor (sem tantos padrões de encoding quebrado), ele é usado no lugar do texto do PyMuPDF.

Na prática, isso reduz a quantidade de casos em que ainda é necessário chamar a etapa de `text_processing` (LLM) apenas para corrigir encoding, embora a lógica de `TextProcessor.clean_text` continue existindo como último recurso em pontos específicos do pipeline.

Ou seja: só os **dicionários JSON** (metadados, artigos, etc.) são gravados em disco; o **texto do PDF já corrigido** que alimenta esses dicionários **não** é guardado em arquivo, mesmo agora com a camada PyMuPDF → validador → `pdftotext` antes da LLM.

---

## Onde cada dado é salvo

| Dado | Arquivo / local | Quando é escrito |
|------|------------------|------------------|
| PDFs baixados | `output/{ano}/pdfs/*.pdf` | Cada PDF ao ser baixado |
| **Texto do PDF corrigido** (saída do `text_processing`) | **Não é salvo** | Apenas em memória; perdido se abortar |
| Cache do site | `output/{ano}/logs/website_articles_cache.json` | Uma vez, após buscar todos os artigos do site |
| **Cache de extração** (PDF → metadados do artigo) | `output/{ano}/logs/extraction_cache.json` | **Após cada artigo** processado na extração |
| Metadados antes do field completion | `output/{ano}/logs/articles_metadata_antes_do_field_completion.json` | **Uma vez**, ao final de `extract_metadata()` (todos os artigos já mergeados) |
| **Cache de field completion** (leitura) | `output/{ano}/logs/articles_metadata_apos_do_field_completion.json` | Carregado no início de `complete_missing_fields()` (resultado de uma execução anterior) |
| Metadados após field completion | `output/{ano}/logs/articles_metadata_apos_do_field_completion.json` | **Uma vez**, ao final de `complete_missing_fields()` (todos os artigos completados) |
| CSVs finais | `output/{ano}/csv/Artigos.csv`, `Autores.csv`, `Referencias.csv` | **Uma vez**, ao final de `complete_missing_fields()` |
| Log de chamadas à IA | `output/{ano}/logs/ai_calls.log.jsonl` | **A cada chamada** à LLM (cada linha = uma chamada; campo `step` indica a etapa: `text_processing`, `field_completion`, `article_extraction`, etc.) |

---

## Se o programa abortar no meio

### Durante o download dos PDFs

- PDFs já baixados permanecem em `output/{ano}/pdfs/`.
- Na próxima execução, o downloader pode pular arquivos já existentes (depende da implementação).

### Durante a extração (PDF → metadados do artigo)

- **Persistência por artigo**: o cache `extraction_cache.json` é gravado **após cada artigo**.
- Se abortar após processar, por exemplo, 30 artigos, esses 30 ficam no cache.
- Na próxima execução, o extractor carrega o cache e **pula** os artigos já presentes; processa só os restantes.
- **Conclusão**: boa recuperação; não é necessário reprocessar do zero.

### Entre a extração e o field completion

- O arquivo `articles_metadata_antes_do_field_completion.json` só é escrito **no fim** de `extract_metadata()`.
- Se abortar no meio da extração, você ainda tem apenas o `extraction_cache.json` (por artigo).
- Se abortar depois de terminar a extração mas antes de começar o field completion, o arquivo "antes" já existe e a ferramenta `regenerate_csv_from_json` pode usar esse JSON (sem field completion).

### Durante o field completion

- O arquivo `articles_metadata_apos_do_field_completion.json` é escrito **apenas uma vez**, ao final de `complete_missing_fields()`, com a lista completa de artigos.
- **Não há gravação incremental por artigo** nessa fase.
- Se abortar após completar, por exemplo, 50 artigos na mesma execução, esses 50 **não** são salvos em "apos_do_field_completion"; na próxima execução o programa usa o arquivo da execução anterior (se existir) e **reprocessa** todos os artigos que ainda têm campos vazios (ou todos, se não houver arquivo anterior).
- **Conclusão**: em caso de aborto no meio do field completion, o progresso dessa execução nessa fase se perde; apenas o que já estava em uma execução anterior completa é reaproveitado.

### Resumo

| Fase | Persistência por artigo? | Em caso de aborto |
|------|---------------------------|-------------------|
| Download PDFs | Sim (arquivo por arquivo) | OK; pode retomar |
| Extração (PDF → artigo) | Sim (`extraction_cache.json` atualizado a cada artigo) | OK; retoma pelo cache |
| Field completion | **Não** (escrita só no fim) | Progresso da execução atual perdido nessa fase |
| CSVs | Não (escritos no fim) | Só existem se a execução terminar |

---

## Uso com LangGraph (processar um artigo por vez)

Para um grafo LangGraph que processe **um único artigo** do início ao fim (texto do PDF → correção de encoding → extração de metadados → field completion) e depois passe para o próximo:

1. **Persistência por artigo**: vale a pena gravar o resultado de **cada** artigo assim que ele terminar (por exemplo, append em um JSONL ou atualização de um JSON por `id_jems`), em vez de acumular tudo em memória e escrever só no fim.
2. **Checkpoint por nó**: o LangGraph pode marcar “artigo X concluído” após o nó de field completion e, em caso de aborto, retomar apenas os artigos ainda não concluídos.
3. **Reutilizar o cache atual**: o `extraction_cache.json` já é um bom modelo de “por artigo”; o mesmo padrão pode ser usado para um “completion_cache” incremental (por exemplo, um JSON que mapeia `id_jems` → artigo completo, atualizado após cada field completion).
4. **Texto corrigido**: hoje o texto do PDF corrigido pela LLM não é salvo; em um grafo por artigo, pode fazer sentido persistir esse texto (ex.: `output/{ano}/logs/corrected_text/{id_jems}.txt`) para não precisar chamar de novo o `text_processing` se a execução abortar ou para reutilizar em field completion.
5. **Log de chamadas**: o `ai_calls.log.jsonl` já registra cada chamada à LLM com o campo **`step`** (`text_processing`, `field_completion`, `article_extraction`, etc.), o que facilita depurar e alinhar com traces no LangSmith.

Sugestão para o grafo: um nó “persist_article” no final do fluxo de um artigo que atualize um arquivo de estado (por exemplo `output/{ano}/logs/completion_cache.json` ou um JSONL) com o artigo completo; e um nó inicial “load_state” que carregue esse estado e determine quais artigos ainda faltam processar.
