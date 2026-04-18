# src/domain/article.py
import ast
from typing import Any, Dict

from src.domain.base_model import BaseModel


def _strip_outer_single_quotes(s: str) -> str:
    """Remove one layer of surrounding single quotes; unescape doubled quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _normalize_keywords_inner(raw: str) -> str:
    """Collapse legacy separators ( ; | ) into comma+space for the cell body."""
    t = _strip_outer_single_quotes(raw.strip())
    if not t:
        return ""
    if " | " in t:
        parts = [p.strip() for p in t.split(" | ") if p.strip()]
        return ", ".join(parts)
    if ";" in t:
        parts = [p.strip() for p in t.split(";") if p.strip()]
        return ", ".join(parts)
    return t


def normalize_keywords_field(value: Any) -> str:
    """
    Coerce keyword metadata to a plain string (comma-separated phrases).

    LLM/JSON often returns lists; str(list) would produce brackets in CSV cells.
    Lists/tuples become \"Teacher training, Technological methodologies, ...\".
    Double-quote wrapping of the CSV field is done by CsvWriter (QUOTE_ALL), not here.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for x in value:
            if x is None:
                continue
            p = str(x).strip()
            if not p:
                continue
            parts.append(_strip_outer_single_quotes(p))
        if not parts:
            return ""
        return ", ".join(parts)
    s = str(value).strip()
    if not s:
        return ""
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return normalize_keywords_field(parsed)
        except (ValueError, SyntaxError):
            pass
    return _normalize_keywords_inner(s)


class Article(BaseModel):
    """
    Represents an academic article with its metadata.

    This class encapsulates all data related to an article, including
    its identification, content, authors, and references.
    """

    # Define the mapping from dictionary keys to object attributes
    field_mapping = {
        "id_jems": "id_jems",
        "idJEMS": "id_jems",  # For backward compatibility
        "titleOrig": "title_orig",
        "titleEn": "title_en",
        "abstractOrig": "abstract_orig",
        "abstractEn": "abstract_en",
        "keywordsOrig": "keywords_orig",
        "keywordsEn": "keywords_en",
        "language": "language",
        "sectionAbbrev": "section_abbrev",
        "firstPage": "first_page",
        "pages": "pages",
        "doi": "doi",
        "numPages": "num_pages",
    }

    # Define the reverse mapping from object attributes to dictionary keys
    reverse_field_mapping = {
        "id_jems": "id_jems",  # Primary key name
        "title_orig": "titleOrig",
        "title_en": "titleEn",
        "abstract_orig": "abstractOrig",
        "abstract_en": "abstractEn",
        "keywords_orig": "keywordsOrig",
        "keywords_en": "keywordsEn",
        "language": "language",
        "section_abbrev": "sectionAbbrev",
        "first_page": "firstPage",
        "pages": "pages",
        "doi": "doi",
        "num_pages": "numPages",
    }

    def __init__(
        self,
        id_jems: str = "",
        title_orig: str = "",
        title_en: str = "",
        abstract_orig: str = "",
        abstract_en: str = "",
        keywords_orig: str = "",
        keywords_en: str = "",
        language: str = "pt",
        section_abbrev: str = "",
        first_page: str = "",
        pages: str = "",
        doi: str = "",
        num_pages: int = 0,
        authors=None,
        references=None,
        **kwargs
    ):
        """
        Initialize an Article object.

        Args:
            id_jems: Article's identifier in the JEMS system
            title_orig: Original title (in language of origin)
            title_en: English title
            abstract_orig: Original abstract (in language of origin)
            abstract_en: English abstract
            keywords_orig: Original keywords (in language of origin)
            keywords_en: English keywords
            language: Language code (default 'pt' for Portuguese)
            section_abbrev: Abbreviated section name
            first_page: First page number
            pages: Page range
            doi: Digital Object Identifier
            num_pages: Number of pages
            authors: List of article authors
            references: List of article references
            **kwargs: Additional attributes
        """
        self.id_jems = id_jems
        self.title_orig = title_orig
        self.title_en = title_en
        self.abstract_orig = abstract_orig
        self.abstract_en = abstract_en
        self.keywords_orig = normalize_keywords_field(keywords_orig)
        self.keywords_en = normalize_keywords_field(keywords_en)
        self.language = language
        self.section_abbrev = section_abbrev
        self.first_page = first_page
        self.pages = pages
        self.doi = doi
        self.num_pages = num_pages

        # Initialize relationships using the base class method
        self.authors = self._initialize_related_objects("Author", authors)
        self.references = self._initialize_related_objects("Reference", references)

        # Handle additional attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Article":
        """
        Create an Article object from a dictionary.

        Args:
            data: Dictionary containing article data

        Returns:
            Article: New Article instance with data from dictionary
        """
        # Create a copy to avoid modifying the original dictionary
        article_data = data.copy()

        # Handle special fields
        authors = article_data.pop("authors", [])
        references = article_data.pop("references", [])

        for _kw in ("keywordsOrig", "keywordsEn"):
            if _kw in article_data:
                article_data[_kw] = normalize_keywords_field(article_data[_kw])

        # Use the parent class method to create the article
        article = super().from_dict(article_data)

        # Populate relationships
        article.authors = article._initialize_related_objects("Author", authors)
        article.references = article._initialize_related_objects(
            "Reference", references
        )

        return article

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the Article object to a dictionary.

        Returns:
            Dict: Dictionary representation of the article
        """
        # Get the base dictionary from the parent class method
        result = super().to_dict()

        # Add the related objects
        result["idJEMS"] = self.id_jems  # For backward compatibility
        result["authors"] = [author.to_dict() for author in self.authors]
        result["references"] = [reference.to_dict() for reference in self.references]

        return result
