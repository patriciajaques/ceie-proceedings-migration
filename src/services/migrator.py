# src/services/migrator.py
from src.config.config_loader import ConfigLoader
from src.services.pdf_downloader import PDFDownloader
from src.utils.pdf_processor import PDFProcessor
from src.services.anais_ojs_html_parser import OJSHTMLParser
from src.services.article_extractor import ArticleExtractor
from src.io.csv_writer import CsvWriter
from src.logging.json_logger import JsonLogger
from src.domain.article import Article
import os


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
        self.doi_prefix = config_loader.get_config_value("doi_prefix")

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

        # 2) Extract article information from the website into a list of dictionaries
        website_articles_data_list = self.parser.extract_articles_info_from_the_website(
            num_files
        )

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

        # 6) Write article information to CSV files
        # First, write all articles together
        csv_writer = CsvWriter(
            self.csv_save_dir, "Artigos.csv", "Autores.csv", "Referencias.csv", True
        )
        csv_writer.write_dicts_to_csv(articles_list)

        # 7) Write CSV files separated by workshop/section
        self.write_csv_by_workshop(articles_list, True)

        return articles_list

    def complete_missing_fields(self, articles_list):
        """
        Completes missing fields in article metadata using AI.

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

        # Complete missing fields in articles using AI
        updated_articles = self.extractor.do_field_completion_of_missing_values_in_dic(
            articles_list
        )

        # Log article metadata after field completion (convert to dict for logging)
        updated_articles_dict = [article.to_dict() for article in updated_articles]
        JsonLogger.print_json(
            "articles_metadata_apos_do_field_completion", updated_articles_dict
        )

        # Write article information to CSV files
        csv_writer = CsvWriter(
            self.csv_save_dir, "Artigos.csv", "Autores.csv", "Referencias.csv", False
        )
        csv_writer.write_dicts_to_csv(updated_articles)

        # Write CSV files separated by workshop/section
        self.write_csv_by_workshop(updated_articles, False)

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

        # Process each item in website_articles_data_list
        for website_article in website_articles_data_list:
            idJEMS = website_article["idJEMS"]
            if idJEMS in pdf_articles_dict:
                pdf_article = pdf_articles_dict[idJEMS]

                # Create a base Article from the website data
                merged_article = Article.from_dict(website_article)

                # Update with PDF article data
                for attr, value in pdf_article.__dict__.items():
                    # Skip certain fields we want to keep from website data
                    if attr not in [
                        "id_jems",
                        "section_abbrev",
                        "first_page",
                        "num_pages",
                    ]:
                        setattr(merged_article, attr, value)

                # Update pages field
                merged_article.pages = self.update_pages(
                    website_article["firstPage"], pdf_article.num_pages
                )

                # Correct DOI
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

    def correct_doi(self, article):
        """
        Corrects the DOI field in the article.

        Args:
            article (Article): Article object to correct.
        """
        if hasattr(article, "first_page") and article.first_page:
            article.doi = f"{self.doi_prefix}{self.year}.{article.first_page}"

    def write_csv_by_workshop(self, articles_list, antes=True):
        """
        Writes CSV files separated by workshop/section.

        Args:
            articles_list (list): List of Article objects.
            antes (bool): If True, adds 'antes_' prefix to filenames.
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
                antes,
            )
            csv_writer.write_dicts_to_csv(workshop_articles)

        print(
            f"\nCSV files by workshop created in {os.path.join(self.csv_save_dir, 'por_workshop')}"
        )
        print(f"Total workshops processed: {len(workshops)}")
