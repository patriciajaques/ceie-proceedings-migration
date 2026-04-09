# src/domain/article.py
from typing import Dict, Any
from src.domain.base_model import BaseModel


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
        self.keywords_orig = keywords_orig
        self.keywords_en = keywords_en
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
