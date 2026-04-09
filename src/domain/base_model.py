# src/domain/base_model.py
from typing import Dict, Any, ClassVar, List, Optional


class BaseModel:
    """
    Base class for domain models with common functionality.

    Provides shared functionality for converting between dictionaries
    and domain objects.
    """

    # Field mappings from dict keys to constructor args - to be defined by subclasses
    field_mapping: ClassVar[Dict[str, str]] = {}

    # Reverse field mapping for to_dict conversion - to be defined by subclasses
    reverse_field_mapping: ClassVar[Dict[str, str]] = {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseModel":
        """
        Create an instance from a dictionary.

        Args:
            data: Dictionary containing model data

        Returns:
            Object: New instance with data from dictionary
        """
        # Map dictionary keys to constructor parameter names
        constructor_args = {}

        # Use the field mapping if defined
        if cls.field_mapping:
            for dict_key, attr_name in cls.field_mapping.items():
                if dict_key in data:
                    constructor_args[attr_name] = data[dict_key]

        # Include other keys that aren't in the mapping
        for key, value in data.items():
            # If the key isn't mapped and isn't an internal attribute
            if (
                not cls.field_mapping or key not in cls.field_mapping
            ) and not key.startswith("_"):
                constructor_args[key] = value

        return cls(**constructor_args)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the object to a dictionary.

        Returns:
            Dict: Dictionary representation of the object
        """
        # Create mapping to convert attribute names to dictionary keys
        # If reverse_field_mapping is defined by subclass, use it
        # Otherwise, generate a reverse mapping from field_mapping
        mapping = getattr(self.__class__, "reverse_field_mapping", {})
        if not mapping and self.__class__.field_mapping:
            mapping = {attr: key for key, attr in self.__class__.field_mapping.items()}

        # Dictionary to store the result
        result = {}

        # Add all attributes to the result dictionary
        for attr, value in self.__dict__.items():
            if not attr.startswith("_"):  # Skip internal attributes
                # Use mapped name if available, otherwise use attribute name
                dict_key = mapping.get(attr, attr)
                result[dict_key] = value

        return result

    def _initialize_related_objects(
        self, class_name: str, data_list: Optional[List[Any]]
    ) -> List[Any]:
        """
        Initialize related objects (authors, references, etc.) from data.

        Args:
            class_name (str): Name of the related class ('Author', 'Reference', etc.)
            data_list (list): List of data items (objects or dictionaries)

        Returns:
            list: List of domain objects
        """
        if not data_list:
            return []

        # Dynamically import classes - note this is done here to avoid circular imports
        from src.domain.author import Author
        from src.domain.reference import Reference

        class_map = {"Author": Author, "Reference": Reference}

        cls = class_map.get(class_name)
        if not cls:
            return []

        result = []
        for item in data_list:
            if isinstance(item, dict):
                result.append(cls.from_dict(item))
            elif isinstance(item, cls):
                result.append(item)

        return result
