# src/io/csv_writer.py
import csv
import json
import os
from src.domain.article import Article
from typing import List, Union, Dict, Any, Callable


class CsvWriter:
    """
    Responsible for writing articles data to CSV files.

    This class handles the conversion of domain objects to CSV format,
    writing articles, authors, and references to separate CSV files.
    """

    def __init__(
        self,
        save_directory,
        path_artigos_csv,
        path_autores_csv,
        path_references_csv,
        antes=True,
        config_path="config/headers.json",
    ):
        """
        Initialize the CSV writer.

        Args:
            save_directory (str): Directory to save the CSV files
            path_artigos_csv (str): Filename for the articles CSV
            path_autores_csv (str): Filename for the authors CSV
            path_references_csv (str): Filename for the references CSV
            antes (bool): If True, adds 'antes_' prefix to filenames
            config_path (str): Path to the JSON file with header configuration
        """
        prefix = "antes_" if antes else ""
        self.save_directory = save_directory
        self.path_artigos_csv = f"{save_directory}/{prefix}{path_artigos_csv}"
        self.path_autores_csv = f"{save_directory}/{prefix}{path_autores_csv}"
        self.path_references_csv = f"{save_directory}/{prefix}{path_references_csv}"

        # Load headers from configuration file
        self.headers_artigos, self.headers_autores, self.headers_references = (
            self.load_headers(config_path)
        )

    def load_headers(self, config_path):
        """
        Load CSV headers from a configuration file.

        Args:
            config_path (str): Path to the JSON configuration file

        Returns:
            tuple: Headers for articles, authors, and references
        """
        with open(config_path, "r") as json_file:
            headers_dict = json.load(json_file)
        return (
            headers_dict["headers_artigos"],
            headers_dict["headers_autores"],
            headers_dict["headers_references"],
        )

    def write_to_csv(self, path, headers, data_list, process_function):
        """
        Write data to a CSV file.

        Args:
            path (str): Path to the CSV file
            headers (list): CSV column headers
            data_list (list): List of data objects to write
            process_function (callable): Function to process each data item
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile, 
                fieldnames=headers, 
                delimiter=";",
                quoting=csv.QUOTE_ALL,
                escapechar=None,
                doublequote=True
            )
            writer.writeheader()
            for seq, data in enumerate(data_list, start=1):
                process_function(writer, seq, data)

    def process_data(self, object_or_dict, headers, extra_data=None):
        """
        Generic method to process data objects or dictionaries.

        Args:
            object_or_dict: Object or dictionary to process
            headers (list): Fields to include in the result
            extra_data (dict, optional): Additional data to include

        Returns:
            dict: Dictionary with fields from headers
        """
        try:
            # Get the data as a dictionary
            if hasattr(object_or_dict, "to_dict"):
                data = object_or_dict.to_dict()
            else:
                data = {key: object_or_dict.get(key, "") for key in headers}

            # Add extra data if provided
            if extra_data:
                data.update(extra_data)

            # Filter to include only fields in headers
            return {key: data.get(key, "") for key in headers}

        except AttributeError as e:
            print(f"Erro ao processar dados: {e}")
            print(f"Tipo do objeto: {type(object_or_dict)}")
            if isinstance(object_or_dict, str):
                print(f"Erro: objeto é uma string: *{object_or_dict}*")
            return {}

    def _get_items_from_article(self, article, attribute_name):
        """
        Get items (authors or references) from an article object or dictionary.

        Args:
            article: Article object or dictionary
            attribute_name (str): Name of the attribute to get ('authors' or 'references')

        Returns:
            list: Items from the article
        """
        return (
            getattr(article, attribute_name)
            if hasattr(article, attribute_name)
            else article.get(attribute_name, [])
        )

    def process_items_data(
        self, writer, seq, article, attribute_name, headers, additional_fields=None
    ):
        """
        Process items (authors or references) data for CSV writing.

        Args:
            writer (csv.DictWriter): CSV writer object
            seq (int): Sequence number
            article: Article object or dictionary
            attribute_name (str): Name of the attribute to process ('authors' or 'references')
            headers (list): Fields to include in the result
            additional_fields (dict, optional): Additional fields to include
        """
        items = self._get_items_from_article(article, attribute_name)

        for i, item in enumerate(items, start=1):
            item_data = {"article": seq, "order": i}
            if additional_fields:
                item_data.update(additional_fields)

            row_data = self.process_data(item, headers, item_data)
            if row_data:
                writer.writerow(row_data)

    def process_artigos_data(self, writer, seq, article):
        """
        Process article data for CSV writing.

        Args:
            writer (csv.DictWriter): CSV writer object
            seq (int): Sequence number
            article (Article): Article object or dictionary
        """
        row_data = self.process_data(article, self.headers_artigos, {"seq": seq})
        if row_data:
            writer.writerow(row_data)

    def process_autores_data(self, writer, seq, article):
        """
        Process authors data for CSV writing.

        Args:
            writer (csv.DictWriter): CSV writer object
            seq (int): Sequence number
            article (Article): Article object or dictionary
        """
        self.process_items_data(writer, seq, article, "authors", self.headers_autores)

    def process_references_data(self, writer, seq, article):
        """
        Process references data for CSV writing.

        Args:
            writer (csv.DictWriter): CSV writer object
            seq (int): Sequence number
            article (Article): Article object or dictionary
        """
        self.process_items_data(
            writer, seq, article, "references", self.headers_references
        )

    def write_dicts_to_csv(self, articles_data):
        """
        Write objects to CSV files.

        Args:
            articles_data (list): List of Article objects or dictionaries
        """
        self.write_to_csv(
            self.path_artigos_csv,
            self.headers_artigos,
            articles_data,
            self.process_artigos_data,
        )
        self.write_to_csv(
            self.path_autores_csv,
            self.headers_autores,
            articles_data,
            self.process_autores_data,
        )
        self.write_to_csv(
            self.path_references_csv,
            self.headers_references,
            articles_data,
            self.process_references_data,
        )
        print(f"CSV files created in {self.save_directory}")

    @staticmethod
    def write_sections_csv(save_directory, sections_data):
        """
        Write sections data to a CSV file.
        
        Args:
            save_directory (str): Directory to save the CSV file
            sections_data (list): List of dictionaries containing section information
        """
        headers_sections = [
            "sectionTitle",
            "sectionTitleEn",
            "sectionAbbrev",
            "blind",
            "numSubmitted",
            "numAccepted",
            "dateSub",
            "dateResult",
            "dateReady",
        ]
        
        path_sections_csv = f"{save_directory}/Secoes.csv"
        
        os.makedirs(save_directory, exist_ok=True)
        
        with open(path_sections_csv, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile, 
                fieldnames=headers_sections, 
                delimiter=";",
                quoting=csv.QUOTE_ALL,
                escapechar=None,
                doublequote=True
            )
            writer.writeheader()
            for section_data in sections_data:
                # Filter to include only fields in headers
                row_data = {
                    key: section_data.get(key, "") for key in headers_sections
                }
                writer.writerow(row_data)
        
        print(f"Secoes.csv created in {save_directory}")
