"""
Script utilitário para (re)gerar os arquivos CSV de artigos, autores e referências
com base nos arquivos JSON de log já existentes.

Objetivo principal
------------------
- Permitir que você gere **versões parciais e atualizadas dos CSVs** a qualquer
  momento, mesmo que a última execução completa da migração tenha sido
  interrompida.

Como funciona
-------------
- Tenta primeiro carregar o JSON **após** o field completion:
    - ``articles_metadata_apos_do_field_completion.json``
- Se esse arquivo ainda não existir, faz um fallback para o JSON **antes**
  do field completion:
    - ``articles_metadata_antes_do_field_completion.json``
- Converte cada dicionário em um objeto ``Article``.
- Usa o mesmo ``CsvWriter`` já utilizado no fluxo principal para gerar:
    - ``Artigos.csv``
    - ``Autores.csv``
    - ``Referencias.csv``
  dentro de ``output/{ano}/csv`` (usando os valores de ``output_dir`` e
  ``year`` em ``config/config.json``).

Quando usar
-----------
- Depois de uma execução longa que foi interrompida (por exemplo, por falta
  de créditos de IA ou por você ter parado manualmente).
- Quando quiser inspecionar rapidamente como está o estado atual dos
  metadados sem precisar rodar toda a pipeline de novo.

Exemplo de uso
--------------
No diretório raiz do projeto (onde está ``src/main.py``), execute:

    python -m src.tools.regenerate_csv_from_json

Requisitos
----------
- ``config/config.json`` deve estar configurado corretamente.
- Pelo menos um dos arquivos JSON deve existir em
  ``output/{ano}/logs``:
    - ``articles_metadata_apos_do_field_completion.json`` (preferido), ou
    - ``articles_metadata_antes_do_field_completion.json``.
"""

from pathlib import Path
from dotenv import load_dotenv
from src.config.config_loader import ConfigLoader
from src.logging.json_logger import JsonLogger
from src.io.csv_writer import CsvWriter
from src.domain.article import Article


def _load_articles_from_logs(config_loader: ConfigLoader):
    """
    Carrega a lista de artigos a partir dos arquivos de log JSON.

    Estratégia:
    - Tenta primeiro o arquivo "apos_do_field_completion" (estado mais completo).
    - Se não existir, faz fallback para o arquivo "antes_do_field_completion".

    Returns:
        list[Article]: Lista de objetos Article carregados do JSON.
    """
    # Inicializa o JsonLogger para garantir que ele use o mesmo diretório base
    JsonLogger.initialize(config_loader)

    # Tenta usar o JSON "após" (estado final, com field completion)
    try:
        articles_dict_list = JsonLogger.read_json_file(
            "articles_metadata_apos_do_field_completion.json"
        )
        print(
            "Carregado JSON 'articles_metadata_apos_do_field_completion.json' "
            "para geração dos CSVs."
        )
    except FileNotFoundError:
        # Fallback para o JSON "antes" (sem field completion aplicado)
        articles_dict_list = JsonLogger.read_json_file(
            "articles_metadata_antes_do_field_completion.json"
        )
        print(
            "Aviso: 'articles_metadata_apos_do_field_completion.json' não encontrado.\n"
            "Usando 'articles_metadata_antes_do_field_completion.json' como fonte "
            "para geração dos CSVs."
        )

    # Garante que, se for um dicionário com chave "data", pegamos a lista interna
    if isinstance(articles_dict_list, dict) and "data" in articles_dict_list:
        articles_dict_list = articles_dict_list["data"]

    articles_list = [Article.from_dict(d) for d in articles_dict_list]
    print(f"Total de artigos carregados do JSON: {len(articles_list)}")
    return articles_list


def regenerate_csv_from_json():
    """
    Regera os arquivos CSV (Artigos, Autores e Referencias) a partir dos JSONs.

    Passos:
    1. Carrega a configuração de ``config/config.json``.
    2. Lê os artigos a partir dos JSONs de log existentes.
    3. Cria um ``CsvWriter`` apontando para ``output/{ano}/csv``.
    4. Gera os arquivos:
        - Artigos.csv
        - Autores.csv
        - Referencias.csv
    """
    # 0) Carregar variáveis de ambiente do arquivo .env na raiz do projeto, se existir
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path)

    # 1) Carregar configuração
    config_loader = ConfigLoader("config/config.json")

    # 2) Carregar artigos a partir dos logs JSON
    articles_list = _load_articles_from_logs(config_loader)

    # 3) Determinar diretório de saída dos CSVs (mesma lógica do Migrator)
    output_dir = config_loader.get_config_value("output_dir")
    year = config_loader.get_config_value("year")
    csv_save_dir = f"{output_dir}{year}/csv"

    # 4) Gerar CSVs finais (sem prefixo "antes_")
    csv_writer = CsvWriter(
        csv_save_dir,
        "Artigos.csv",
        "Autores.csv",
        "Referencias.csv",
        antes=False,
    )
    csv_writer.write_dicts_to_csv(articles_list)

    print("\nRegeneração de CSVs concluída.")
    print(f"Arquivos gerados em: {csv_save_dir}")


def main():
    """
    Ponto de entrada para execução via linha de comando.

    Permite rodar:

        python -m src.tools.regenerate_csv_from_json
    """
    regenerate_csv_from_json()


if __name__ == "__main__":
    main()

