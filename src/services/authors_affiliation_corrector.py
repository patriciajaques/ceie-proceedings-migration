import numpy as np
import pandas as pd
import os
from src.adapters.ai_client_interface import AIClientInterface
from src.services.article_extractor import ArticleExtractor
from src.config.config_loader import ConfigLoader
from src.domain.author import Author


class AuthorsAffiliationCorrector:
    """
    Class for correcting author affiliation information in CSV files.

    This class processes author affiliation data, corrects it using AI,
    and updates the CSV file with the corrected information.
    """

    def __init__(self, config_loader, ai_client, article_extractor):
        """
        Initializes the AuthorsAffiliationCorrector with injected dependencies.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            ai_client (AIClientInterface): AI client for corrections.
            article_extractor (ArticleExtractor): Extractor for processing data.
        """
        # Store injected dependencies
        self.config_loader = config_loader
        self.assistant = ai_client
        self.extractor = article_extractor

        # Generate folder based on output_dir and year
        output_dir = config_loader.get_config_value("output_dir")
        year = config_loader.get_config_value("year")
        self.folder = os.path.join(output_dir, f"{year}", "csv")

    def process_affiliation_chunk(self, chunk):
        """
        Process a chunk of affiliation data using AI.

        Args:
            chunk (DataFrame): DataFrame chunk containing affiliation data

        Returns:
            list: Processed affiliation data as a list of dictionaries
        """
        chunk_csv = chunk.to_csv(sep=";", index=False)
        result = self.extractor.extract_info_with_ai(
            self.assistant, chunk_csv, recursion_count=0
        )

        # Handle different return formats from AI
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            if "universidades" in result and isinstance(result["universidades"], list):
                return result["universidades"]
            else:
                return [result]
        return []

    def load_authors_data(self):
        """
        Load authors data from CSV file.

        Returns:
            DataFrame: Authors data as a pandas DataFrame
        """
        csv_path = f"{self.folder}/Autores.csv"
        return pd.read_csv(csv_path, delimiter=";")

    # DISABLED: Método desabilitado para evitar geração de Autores_corrigido.csv
    # def save_corrected_data(self, authors_df):
    #     """
    #     Save corrected authors data to CSV file.
    #
    #     Args:
    #         authors_df (DataFrame): Corrected authors DataFrame
    #     """
    #     # Specify the column order
    #     columns_order = [
    #         "article",
    #         "authorFirstName",
    #         "authorMiddleName",
    #         "authorLastName",
    #         "authorAffiliation",
    #         "authorAffiliationEn",
    #         "authorCountry",
    #         "authorEmail",
    #         "orcid",
    #         "order",
    #     ]
    #
    #     # Reorder the DataFrame columns
    #     authors_df = authors_df[columns_order]
    #
    #     # Remove duplicate rows
    #     authors_df = authors_df.drop_duplicates()
    #
    #     # Generate the CSV file
    #     authors_df.to_csv(f"{self.folder}/Autores_corrigido.csv", sep=";", index=False)

    def convert_to_domain_objects(self, authors_df):
        """
        Convert DataFrame rows to Author domain objects.

        Args:
            authors_df (DataFrame): Authors DataFrame

        Returns:
            list: List of Author domain objects
        """
        authors = []
        for _, row in authors_df.iterrows():
            author = Author(
                first_name=row["authorFirstName"],
                middle_name=row["authorMiddleName"],
                last_name=row["authorLastName"],
                affiliation=row["authorAffiliation"],
                affiliation_en=row["authorAffiliationEn"],
                country=row["authorCountry"],
                email=row["authorEmail"],
                orcid=row["orcid"],
                order=row["order"],
            )
            author.article_id = row["article"]
            authors.append(author)
        return authors

    def split_into_chunks(self, df, chunk_size=20):
        """
        Split DataFrame into chunks for processing.

        Args:
            df (DataFrame): DataFrame to split
            chunk_size (int): Size of each chunk

        Returns:
            list: List of DataFrame chunks
        """
        return [group for _, group in df.groupby(np.arange(len(df)) // chunk_size)]

    def merge_and_update_dataframe(self, authors_df, dict_list):
        """
        Merge processed affiliation data with original authors DataFrame.

        Args:
            authors_df (DataFrame): Original authors DataFrame
            dict_list (list): List of processed affiliation dictionaries

        Returns:
            DataFrame: Updated DataFrame with corrected affiliations
        """
        # Convert dict_list to a DataFrame
        dict_df = pd.DataFrame(dict_list)

        # Rename the affiliation column to avoid conflicts
        dict_df = dict_df.rename(columns={"authorAffiliation": "newAuthorAffiliation"})

        # Remove the authorAffiliationEn column from authors_df
        authors_df = authors_df.drop(columns=["authorAffiliationEn"])

        # Merge authors_df and dict_df
        authors_df = pd.merge(
            authors_df,
            dict_df,
            how="left",
            left_on="authorAffiliation",
            right_on="originalAuthorAffiliation",
        )

        # Drop unnecessary columns
        authors_df = authors_df.drop(
            columns=["originalAuthorAffiliation", "authorAffiliation"]
        )

        # Replace values in the "authorAffiliation" column with values from "newAuthorAffiliation"
        authors_df["authorAffiliation"] = authors_df["newAuthorAffiliation"]

        # Remove extra columns
        authors_df = authors_df.drop(columns=["newAuthorAffiliation"])

        return authors_df

    def correct_affiliation_columns_from_authors_csv(self):
        """
        Corrects affiliation columns in the authors CSV file.

        Reads the authors CSV file, processes the affiliation columns
        using AI, and updates the file with corrected information.

        Returns:
            list: List of Author domain objects with corrected affiliations
        """
        # Load authors data from CSV
        authors_df = self.load_authors_data()

        # Extract only the "authorAffiliation" and "authorAffiliationEn" columns
        authors_aff_df = authors_df[["authorAffiliation", "authorAffiliationEn"]]

        # Split authors_aff_df into chunks of number_of_lines rows
        chunks = self.split_into_chunks(authors_aff_df)

        # Initialize an empty list to store results
        dict_list = []

        # For each chunk, process affiliations with AI
        for chunk in chunks:
            result = self.process_affiliation_chunk(chunk)
            dict_list.extend(result)

        # Merge processed data with original DataFrame
        authors_df = self.merge_and_update_dataframe(authors_df, dict_list)

        print(f"\ndataframefinal:{authors_df}\n\n")

        # Save the corrected data
        # DISABLED: Processo de correção desabilitado - Autores.csv já está correto
        # self.save_corrected_data(authors_df)

        # Convert DataFrame to domain objects
        return self.convert_to_domain_objects(authors_df)


# DISABLED: Bloco __main__ desabilitado para evitar execução acidental
# if __name__ == "__main__":
#     from src.adapters.openai_client import OpenAIClient
#     from src.config.config_loader import ConfigLoader
#     from src.services.article_extractor import ArticleExtractor
#
#     config_loader = ConfigLoader("config/config.json")
#     ai_client = OpenAIClient(config_loader, "author_affiliation_correction")
#     article_extractor = ArticleExtractor(ai_client, ai_client, ai_client)
#     corrector = AuthorsAffiliationCorrector(config_loader, ai_client, article_extractor)
#     corrector.correct_affiliation_columns_from_authors_csv()
