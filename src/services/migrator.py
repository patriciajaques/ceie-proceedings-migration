# src/services/migrator.py
import json
from src.config.config_loader import ConfigLoader
from src.services.pdf_downloader import PDFDownloader
from src.utils.pdf_processor import PDFProcessor
from src.services.anais_ojs_html_parser import OJSHTMLParser
from src.services.article_extractor import ArticleExtractor
from src.io.csv_writer import CsvWriter
from src.logging.json_logger import JsonLogger
from src.domain.article import Article
import os
import re


class Migrator:
    """
    Class responsible for migrating PDF files, processing PDFs and extracting article information.

    This class coordinates the entire migration process, from downloading PDFs from a website,
    processing their content, extracting metadata, to generating CSV files with the extracted data.
    """

    def __init__(
        self, config_loader: ConfigLoader, article_extractor: ArticleExtractor
    ):
        """
        Initializes the Migrator with the necessary components.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            article_extractor (ArticleExtractor): Article extractor instance.
        """
        # Load configuration values
        self.site_url = config_loader.get_config_value("site_url")
        self.output_dir = config_loader.get_config_value("output_dir")
        self.year = config_loader.get_config_value("year")
        # doi_prefix is now optional - will be inferred from extracted DOIs if not provided
        self.doi_prefix = config_loader.get_config_value("doi_prefix", None)
        self.inferred_doi_prefix = None  # Will be set after extracting DOIs

        # Generate directories based on year
        self.pdf_save_dir = os.path.join(self.output_dir, f"{self.year}", "pdfs")
        self.csv_save_dir = os.path.join(self.output_dir, f"{self.year}", "csv")

        # Ensure directories exist
        os.makedirs(self.pdf_save_dir, exist_ok=True)
        os.makedirs(self.csv_save_dir, exist_ok=True)

        self.downloader = PDFDownloader(self.site_url, self.pdf_save_dir)
        self.processor = PDFProcessor(self.pdf_save_dir)
        self.parser = OJSHTMLParser(self.site_url)
        self.extractor = article_extractor

    def migrate(self, num_pages=11, num_files=-1):
        """
        Executes the migration process: downloads PDFs, extracts metadata, and generates CSV files.

        Args:
            num_pages (int): Number of pages to process from each PDF.
            num_files (int, optional): Number of PDF files to download. Default is -1, which downloads all files.

        Returns:
            list: List of Article objects containing article metadata.
        """
        # 1) Download all PDFs from the specified website to a directory
        self.downloader.donwload_pdf_files_from_url(num_files)

        # 2) Extract article information from the downloaded PDFs
        articles_list = self.extract_metadata(num_files, num_pages)

        # 3) Complete missing fields in the articles by calling the AI API
        self.complete_missing_fields(articles_list)

        # 4) Return the processed metadata
        return articles_list

    def extract_metadata(self, num_files=-1, num_pages=11):
        """
        Extracts metadata from the PDFs and website.

        Args:
            num_files (int, optional): Number of PDF files to process. Default is -1, which processes all files.
            num_pages (int, optional): Number of pages to process from each PDF. Default is 11.

        Returns:
            list: List of Article objects containing article metadata.
        """
        # 1) Process all PDFs in the directory, extracting the text
        all_files_data = self.processor.process_all_pdfs(
            save_files=False, number_of_pages_to_process=num_pages
        )

        # 2) Extract article information from the website (usa cache se existir)
        website_articles_data_list = self._get_website_articles_data(num_files)

        # 2.5) Extract sections from the website and generate Secoes.csv
        sections_data = self.parser.extract_sections_from_website()
        CsvWriter.write_sections_csv(self.csv_save_dir, sections_data)

        # 3) Extract article information from PDF text into a list of Article objects
        pdf_articles_list = self.extractor.extract_articles_data_from_PDF_text(
            all_files_data
        )

        # 4) Merge article information extracted from the website with information from PDFs
        articles_list = self.merge_article_info(
            website_articles_data_list, pdf_articles_list
        )

        # 5) Log article metadata before field completion (convert to dict for logging)
        articles_dict_list = [article.to_dict() for article in articles_list]
        JsonLogger.print_json(
            "articles_metadata_antes_do_field_completion", articles_dict_list
        )

        # Note: CSV files will be generated after field completion in complete_missing_fields()

        return articles_list

    def _get_website_articles_data(self, num_files: int):
        """
        Obtém metadados dos artigos do site. Usa cache em execuções subsequentes
        para evitar novas requisições HTTP ao site.
        """
        cache_path = os.path.join(
            self.output_dir, str(self.year), "logs", "website_articles_cache.json"
        )
        try:
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, list) and cached:
                    print(
                        f"Metadados do site carregados do cache ({len(cached)} artigos)"
                    )
                    if num_files != -1:
                        return cached[:num_files]
                    return cached
        except (json.JSONDecodeError, IOError):
            pass

        # Sempre busca a lista completa para popular o cache
        website_articles_data_list = self.parser.extract_articles_info_from_the_website(
            -1
        )
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(website_articles_data_list, f, ensure_ascii=False, indent=2)
        if num_files != -1:
            return website_articles_data_list[:num_files]
        return website_articles_data_list

    def _load_completion_cache(self):
        """
        Carrega o cache de field completion de execuções anteriores.
        Retorna um dicionário {idJEMS: article_dict} para reutilizar artigos já processados.
        """
        try:
            data = JsonLogger.read_json_file(
                "articles_metadata_apos_do_field_completion.json"
            )
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if isinstance(data, list):
                return {
                    (d.get("idJEMS") or d.get("id_jems", "")): d
                    for d in data
                    if d.get("idJEMS") or d.get("id_jems")
                }
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return {}

    def complete_missing_fields(self, articles_list):
        """
        Completes missing fields in article metadata using AI.

        Usa cache incremental: artigos já completados em execuções anteriores
        são reutilizados e não passam pela IA novamente.

        Args:
            articles_list (list): List of Article objects containing article metadata.

        Returns:
            list: Updated list of Article objects with completed article metadata.
        """
        if not articles_list:
            # Load JSON file with article metadata for testing
            articles_dict_list = JsonLogger.read_json_file(
                "articles_metadata_antes_do_field_completion.json"
            )
            # Convert dictionaries back to Article objects
            articles_list = [
                Article.from_dict(article_dict) for article_dict in articles_dict_list
            ]

        # Carrega cache de field completion de execuções anteriores (incremental)
        completion_cache = self._load_completion_cache()

        # Complete missing fields in articles using AI (usa cache para pular já processados)
        updated_articles = self.extractor.do_field_completion_of_missing_values_in_dic(
            articles_list, completion_cache=completion_cache
        )

        # Log article metadata after field completion (convert to dict for logging)
        updated_articles_dict = [article.to_dict() for article in updated_articles]
        JsonLogger.print_json(
            "articles_metadata_apos_do_field_completion", updated_articles_dict
        )

        # Write article information to CSV files (final version after field completion)
        csv_writer = CsvWriter(
            self.csv_save_dir, "Artigos.csv", "Autores.csv", "Referencias.csv", antes=False
        )
        csv_writer.write_dicts_to_csv(updated_articles)

        # Write CSV files separated by workshop/section
        self.write_csv_by_workshop(updated_articles)

        return updated_articles

    def merge_article_info(self, website_articles_data_list, pdf_articles_list):
        """
        Merges article information from website and PDF sources.

        Args:
            website_articles_data_list (list): List of dictionaries containing article information from the website.
            pdf_articles_list (list): List of Article objects containing article information from PDFs.

        Returns:
            list: List of Article objects with merged article information.
        """
        # Convert pdf_articles_list to a dictionary for O(1) access by key
        pdf_articles_dict = {article.id_jems: article for article in pdf_articles_list}

        # New list for merged articles
        merged_articles_list = []

        # First pass: collect all extracted DOIs to infer prefix if needed
        extracted_dois = []
        for website_article in website_articles_data_list:
            # Check if DOI was extracted from website
            if "doi" in website_article and website_article["doi"]:
                extracted_dois.append(website_article["doi"])

            # Check if DOI was extracted from PDF
            idJEMS = website_article["idJEMS"]
            if idJEMS in pdf_articles_dict:
                pdf_article = pdf_articles_dict[idJEMS]
                if hasattr(pdf_article, "doi") and pdf_article.doi:
                    extracted_dois.append(pdf_article.doi)

        # Infer DOI prefix from extracted DOIs
        if extracted_dois:
            self.inferred_doi_prefix = self._infer_doi_prefix(extracted_dois)
            if self.inferred_doi_prefix:
                print(
                    f"Prefixo DOI inferido automaticamente a partir do site: {self.inferred_doi_prefix}"
                )

        # Process each item in website_articles_data_list
        for website_article in website_articles_data_list:
            idJEMS = website_article["idJEMS"]
            if idJEMS in pdf_articles_dict:
                pdf_article = pdf_articles_dict[idJEMS]

                # Create a base Article from the website data
                merged_article = Article.from_dict(website_article)

                # Update with PDF article data, but preserve DOI from website if it exists
                website_doi = (
                    merged_article.doi if hasattr(merged_article, "doi") else None
                )

                for attr, value in pdf_article.__dict__.items():
                    # Skip certain fields we want to keep from website (Milanesa) data
                    if attr not in [
                        "id_jems",
                        "section_abbrev",
                        "first_page",
                        "num_pages",
                        "doi",  # Preserve DOI from website if available
                        "title_orig",  # Preserve title from website (Milanesa)
                        "title_en",  # Preserve English title (to be filled later)
                        "authors",  # Preserve authors from website (Milanesa)
                        "keywords_orig",  # Preserve keywords from website / later completion
                        "keywords_en",
                    ]:
                        # Normalize DOI if it comes from PDF
                        if attr == "doi" and value:
                            value = self._normalize_doi(value)
                        setattr(merged_article, attr, value)

                # Restore website DOI if it was extracted (normalize it)
                if website_doi:
                    merged_article.doi = self._normalize_doi(website_doi)

                # Update pages field
                merged_article.pages = self.update_pages(
                    website_article["firstPage"], pdf_article.num_pages
                )

                # Correct/generate DOI only if not already extracted
                self.correct_doi(merged_article)

                merged_articles_list.append(merged_article)

        return merged_articles_list

    def update_pages(self, first_page, num_pages):
        """
        Updates the pages field based on first page and number of pages.

        Args:
            first_page (str): First page number as a string.
            num_pages (int): Number of pages.

        Returns:
            str: Updated pages field.
        """
        if first_page and first_page.isdigit():
            first_page_int = int(first_page)
            if num_pages == 1:
                return str(first_page_int)
            else:
                last_page = first_page_int + int(num_pages) - 1
                return f"{first_page_int}-{last_page}"
        else:
            return first_page

    def _normalize_doi(self, doi):
        """
        Normalizes a DOI by removing URL prefixes, keeping only the identifier.

        Args:
            doi (str): DOI string that may include URL prefix.

        Returns:
            str: Normalized DOI identifier (e.g., "10.5753/cbie.wcbie.2019.1")
        """
        if not doi:
            return ""

        # Remove http://, https://, dx.doi.org/, doi.org/ prefixes
        normalized = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip())
        return normalized

    def _infer_doi_prefix(self, dois):
        """
        Infers the DOI base prefix (without year/suffix) from a list of extracted DOIs.

        Args:
            dois (list): List of DOI strings.

        Returns:
            str: Inferred DOI prefix (without the suffix part), or None if cannot infer.
        """
        if not dois:
            return None

        # Normalize DOIs - remove https://doi.org/ prefix if present
        normalized_dois = []
        for doi in dois:
            if not doi:
                continue
            # Remove http/https and doi.org prefixes
            normalized = self._normalize_doi(doi)
            if normalized:
                normalized_dois.append(normalized)

        if not normalized_dois:
            return None

        # Find common base prefix pattern
        # For DOIs like: 10.xxxx/prefix.year.suffix
        # we want to extract a base prefix without year/suffix: 10.xxxx/prefix.
        prefix_patterns = []
        for doi in normalized_dois:
            if "/" not in doi:
                continue

            main_prefix, suffix_part = doi.split("/", 1)
            parts = [p for p in suffix_part.split(".") if p]

            # We expect at least: prefix.year.suffix
            if len(parts) >= 3:
                base_suffix = ".".join(parts[:-2])
            elif len(parts) >= 1:
                # Fallback: use only the first part after the slash
                base_suffix = parts[0]
            else:
                continue

            prefix_patterns.append(f"{main_prefix}/{base_suffix}.")

        if not prefix_patterns:
            return None

        # Find the most common prefix pattern
        from collections import Counter

        prefix_counts = Counter(prefix_patterns)
        most_common = prefix_counts.most_common(1)[0][0]

        # Return normalized prefix (without URL) - just the identifier pattern
        return most_common

    def correct_doi(self, article):
        """
        Corrects or generates the DOI field in the article.
        Uses extracted DOI if available, otherwise generates one using prefix.
        Always stores DOI in normalized format (identifier only, no URL).

        Args:
            article (Article): Article object to correct.
        """
        # If DOI already exists, normalize it and return
        if hasattr(article, "doi") and article.doi and article.doi.strip():
            article.doi = self._normalize_doi(article.doi)
            return

        # Only generate DOI if we have prefix and first_page
        # Prefer the prefix inferred from the website and use the config value as fallback
        doi_prefix = self.inferred_doi_prefix or self.doi_prefix

        if not doi_prefix:
            print(
                "Aviso: Não foi possível gerar DOI - prefixo não disponível e não foi possível inferir."
            )
            return

        if hasattr(article, "first_page") and article.first_page:
            # Normalize prefix (remove URL if present)
            clean_prefix = self._normalize_doi(doi_prefix)
            if not clean_prefix:
                # If prefix was in URL format, try to extract from it
                clean_prefix = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_prefix)
            clean_prefix = clean_prefix.rstrip("/")

            # Generate DOI in normalized format (identifier only, no URL)
            generated_doi = f"{clean_prefix}{self.year}.{article.first_page}"
            article.doi = generated_doi

    def write_csv_by_workshop(self, articles_list):
        """
        Writes CSV files separated by workshop/section.

        Args:
            articles_list (list): List of Article objects.
        """
        # Group articles by section
        workshops = {}
        for article in articles_list:
            section = (
                article.section_abbrev
                if hasattr(article, "section_abbrev")
                else article.to_dict().get("sectionAbbrev", "UNKNOWN")
            )

            if section not in workshops:
                workshops[section] = []
            workshops[section].append(article)

        # Create CSV files for each workshop
        for workshop_name, workshop_articles in workshops.items():
            if not workshop_articles:
                continue

            # Create subdirectory for workshop
            workshop_dir = os.path.join(self.csv_save_dir, "por_workshop")

            csv_writer = CsvWriter(
                workshop_dir,
                f"{workshop_name}_Artigos.csv",
                f"{workshop_name}_Autores.csv",
                f"{workshop_name}_Referencias.csv",
                antes=False,
            )
            csv_writer.write_dicts_to_csv(workshop_articles)

        print(
            f"\nCSV files by workshop created in {os.path.join(self.csv_save_dir, 'por_workshop')}"
        )
        print(f"Total workshops processed: {len(workshops)}")
