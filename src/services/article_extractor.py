import json
import re
from typing import Dict, List, Optional
from src.utils.text_processor import TextProcessor
from src.domain.article import Article
from src.adapters.ai_client_interface import AIClientInterface


class ArticleExtractor:
    """Extracts metadata from articles based on text content.

    This class uses an AI client to extract structured information
    from academic articles based on text extracted from PDFs.
    """

    def __init__(
        self,
        article_ai_client: AIClientInterface,
        references_ai_client: AIClientInterface,
        field_completion_ai_client: AIClientInterface,
        text_processor: Optional[TextProcessor] = None,
    ):
        """Initializes the article extractor.

        Args:
            article_ai_client (AIClientInterface): AI client for article metadata extraction.
            references_ai_client (AIClientInterface): AI client for reference extraction.
            field_completion_ai_client (AIClientInterface): AI client for completing missing fields.
            text_processor (TextProcessor, optional): Text processor for cleaning text.
                If not provided, a new one will be created.
        """
        self.article_ai_client = article_ai_client
        self.references_ai_client = references_ai_client
        self.field_completion_ai_client = field_completion_ai_client
        self.text_processor = text_processor or TextProcessor()

    def extract_articles_data_from_PDF_text(
        self, all_files_text: List[Dict]
    ) -> List[Article]:
        """Extracts article data from PDF text.

        Args:
            all_files_text (list): List of dictionaries containing text extracted from PDFs.

        Returns:
            list: List of Article objects with article metadata.
        """
        articles_list = []

        for count, one_article_text in enumerate(all_files_text, start=1):
            article = self.extract_article_data(one_article_text)
            articles_list.append(article)
            print(f"\n\nProcessed article number {count}\n")

        return articles_list

    def extract_article_data(self, one_article_text: Dict) -> Article:
        """Extracts data from a single article.

        Args:
            one_article_text (dict): Dictionary containing text extracted from a PDF.

        Returns:
            Article: Article object with article metadata.
        """
        first_pages = self.extract_pages(one_article_text, page_location="first")
        first_pages = self.text_processor.clean_text(first_pages)

        last_pages = self.extract_pages(one_article_text, page_location="last")
        last_pages = self.text_processor.clean_text(last_pages)

        # Check if we have section information
        section_abbrev = one_article_text.get("sectionAbbrev", None)

        article_dict = self.extract_metadata_with_ai(
            first_pages, last_pages, section_abbrev
        )

        # Update with additional information
        article_dict["num_pages"] = one_article_text["numPages"]
        article_dict["id_jems"] = one_article_text["base_filename"]
        article_dict["language"] = "pt"

        # Convert to Article object
        return Article.from_dict(article_dict)

    def extract_pages(self, one_article_text: Dict, page_location: str) -> str:
        """Extracts text from specified pages of an article.

        Args:
            one_article_text (dict): Dictionary containing text extracted from a PDF.
            page_location (str): Location of pages to extract ("first" or "last").

        Returns:
            str: Text from the specified pages.
        """
        text_pages = one_article_text["text_pages"]

        if page_location == "first":
            # Strategy for initial pages
            first_page = text_pages[0]

            if len(text_pages) < 2 or any(
                word in first_page.lower()
                for word in ["introducao", "introdução", "introduction"]
            ):
                return str(first_page)
            else:
                second_page = text_pages[1]
                return f"{first_page}, {second_page}"

        elif page_location == "last":
            # Strategy for final pages
            if len(text_pages) == 1:
                return str(text_pages[0])

            last_page = text_pages[-1]
            ref_indicators = [
                "references",
                "referências",
                "referencias",
                "bibliography",
                "bibliografia",
                "referência",
                "referˆencia",
            ]

            if len(text_pages) < 2 or any(
                word in last_page.lower() for word in ref_indicators
            ):
                return str(last_page)
            else:
                third_last_page = text_pages[-3] if len(text_pages) > 3 else ""
                second_last_page = text_pages[-2]
                return f"{third_last_page} {second_last_page} {last_page}"

        # Default behavior for invalid argument
        raise ValueError(f"Invalid page location: {page_location}")

    def extract_metadata_with_ai(
        self, first_pages: str, last_pages: str, section_abbrev: Optional[str] = None
    ) -> Dict:
        """Extracts metadata using AI.

        Args:
            first_pages (str): Text from the first pages of the article.
            last_pages (str): Text from the last pages of the article.
            section_abbrev (str, optional): Section abbreviation. Defaults to None.

        Returns:
            dict: Dictionary with article metadata and references.
        """
        article_dict = self.extract_article_metadata_with_ai(first_pages)
        article_dict["firstPages"] = first_pages
        article_dict["lastPages"] = last_pages

        # Adjust sectionAbbrev field if provided
        if section_abbrev:
            article_dict["sectionAbbrev"] = section_abbrev

        # Only extract references if NOT an editorial
        if section_abbrev != "EDT":
            references_dict = self.extract_references_metadata_with_ai(last_pages)
            article_dict["references"] = references_dict.get("references", [])
        else:
            # For editorials, just add an empty references list
            article_dict["references"] = []

        return article_dict

    def extract_article_metadata_with_ai(self, first_pages: str) -> Dict:
        """Extracts article metadata using AI.

        Args:
            first_pages (str): Text from the first pages of the article.

        Returns:
            dict: Dictionary with article metadata.
        """
        return self.extract_info_with_ai(self.article_ai_client, first_pages)

    def extract_references_metadata_with_ai(self, last_pages: str) -> Dict:
        """Extracts references using AI.

        Args:
            last_pages (str): Text from the last pages of the article.

        Returns:
            dict: Dictionary with extracted references.
        """
        return self.extract_info_with_ai(self.references_ai_client, last_pages)

    def do_field_completion_of_missing_values_in_dic(
        self, articles_list: List[Article]
    ) -> List[Article]:
        """Completes missing fields in article metadata.

        Args:
            articles_list (list): List of Article objects with metadata.

        Returns:
            list: Updated list of Article objects with completed fields.
        """
        updated_articles = []

        for article in articles_list:
            # Convert to dictionary for AI compatibility
            article_dict = article.to_dict()

            if (
                (article_dict.get("titleOrig") or article_dict.get("titleEn"))
                and article_dict.get("sectionAbbrev") != "EDT"
                and self.has_empty_fields(article_dict)
            ):

                print(
                    f"Improving article record with seq "
                    f"{article_dict.get('seq')} and idJEMS: "
                    f"{article_dict.get('idJEMS')}"
                )

                # Remove fields that don't need to be sent to AI
                clean_dict = article_dict.copy()
                clean_dict.pop("firstPages", None)
                clean_dict.pop("lastPages", None)

                new_dict = self.extract_info_with_ai(
                    self.field_completion_ai_client, json.dumps(clean_dict)
                )

                if new_dict and isinstance(new_dict, dict):
                    # Convert the updated dictionary back to an Article object
                    updated_article = Article.from_dict(new_dict)
                    updated_articles.append(updated_article)
                else:
                    updated_articles.append(article)
            else:
                updated_articles.append(article)

        return updated_articles

    def has_empty_fields(self, dictionary: Dict) -> bool:
        """Checks if the dictionary has empty fields.

        Args:
            dictionary (dict): Dictionary to check.

        Returns:
            bool: True if there are empty fields, False otherwise.
        """
        for key, value in dictionary.items():
            # Ignore specific fields and empty lists (which may be valid)
            if (
                key not in ["firstPages", "lastPages", "references"]
                and not value
                and value != 0
            ):
                return True
        return False

    def extract_info_with_ai(
        self, ai_client: AIClientInterface, instruction: str, recursion_count: int = 0
    ) -> Dict:
        """Extracts information using AI.

        Args:
            ai_client (AIClientInterface): AI client for extraction.
            instruction (str): Instruction for the AI.
            recursion_count (int): Recursion counter for limited retry attempts.

        Returns:
            dict: Dictionary with extracted information.
        """
        json_info = ai_client.create_completion(instruction, True)

        try:
            return self.parse_ai_response(json_info)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"\n\n\n**** Error decoding JSON: {e} ***")
            response_preview = json_info[:500] if json_info else "None"
            print(
                f"**** Response received from model (first 500 chars): "
                f"{response_preview} *** \n\n\n"
            )

            # Try again with recursion limit
            if recursion_count < 3:
                return self.extract_info_with_ai(
                    ai_client, instruction, recursion_count + 1
                )

            print("**** Failed after 3 attempts. Returning empty dictionary.")
            return {}

    def parse_ai_response(self, json_info: str) -> Dict:
        """Parses the AI response and extracts JSON.

        Args:
            json_info (str): AI response that should contain JSON.

        Returns:
            dict: Parsed JSON data.

        Raises:
            ValueError: If valid JSON cannot be found.
            json.JSONDecodeError: If the found JSON is not valid.
        """
        # Find the JSON part of the string
        match = re.search(r"\{.*\}|\[.*\]", json_info, re.DOTALL)
        if not match:
            raise ValueError("Could not find valid JSON in the response")

        # Convert JSON string to dictionary
        return json.loads(match.group())
