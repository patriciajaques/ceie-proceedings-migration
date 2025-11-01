from bs4 import BeautifulSoup
from src.services.pdf_downloader import PDFDownloader
from src.config.config_loader import ConfigLoader
import json
import re
from urllib.parse import urlparse, unquote


class OJSHTMLParser:
    def __init__(self, site_url):
        self.site_url = site_url

    def download_html_and_create_parser(self, site_url):
        downloader = PDFDownloader(site_url, "output")
        html_file = downloader.download_file(site_url)
        soup = BeautifulSoup(html_file, "html.parser")
        return soup

    def extract_articles_info_from_the_website(self, num_files_to_process=-1):
        """
        Extracts information about the articles from the HTML file. It extracts the following information:
        - The sequential number of the article
        - The abbreviated section name
        - The original title of the article
        - The starting page of the article

        Args:
            num_files_to_process (int, optional): The number of files to process.
                Default is -1, which processes all files.

        Returns:
            list: A list of dictionaries containing article information.
        """
        metadados_url = ""
        # Data structure to store extracted information
        data = []

        # Sequential number for articles
        seq_num = 1

        soup = self.download_html_and_create_parser(self.site_url)

        # Identify and process each section
        sections = soup.find_all("h4", class_="tocSectionTitle")
        for section in sections:
            section_name = section.text.strip()
            # Generate section abbreviation based on the section name
            section_abbrev = self._generate_section_abbrev(section_name)

            # Find all articles in this section
            next_sibling = section.find_next_sibling()
            while next_sibling and next_sibling.name == "table":
                # Check if we've reached the limit BEFORE processing
                # If num_files_to_process = 5, we want to process articles 1-5 (seq_num 1, 2, 3, 4, 5)
                # So we stop when seq_num > num_files_to_process (i.e., when seq_num = 6)
                if num_files_to_process != -1 and seq_num > num_files_to_process:
                    break

                article_title = next_sibling.find("div", class_="tocTitle").text.strip()
                page_start = next_sibling.find("div", class_="tocPages").text.strip()

                # Attempt to find the PDF link
                pdf_link_element = next_sibling.find("a", href=True, text="PDF")
                if pdf_link_element:
                    pdf_url = pdf_link_element["href"]
                    metadados_url = self.convert_url(pdf_url)
                    parsed_url = urlparse(pdf_url)
                    pdf_file_name = unquote(
                        parsed_url.path.split("/")[-1].replace(".pdf", "")
                    )
                else:
                    pdf_file_name = "No PDF link found"

                # Store the extracted information
                metadados = {
                    "seq": seq_num,
                    "sectionAbbrev": section_abbrev,
                    "titleOrig": article_title,
                    "firstPage": page_start,
                    "idJEMS": pdf_file_name,  # Add the processed PDF file name here
                }
                print("Processando arquivo: ", metadados["idJEMS"])

                # Get additional metadata
                additional_metadata = self.get_metadata(metadados_url)
                print("Pegou metadados adicionais: do arquivo", metadados["idJEMS"])

                # Add items from additional_metadata to metadados, but only if they don't already exist in metadados
                for key, value in additional_metadata.items():
                    if key not in metadados:
                        metadados[key] = value
                    else:
                        metadados[key + str(2)] = value
                data.append(metadados)

                seq_num += 1
                next_sibling = next_sibling.find_next_sibling()

            # Check if we've reached the limit (outside the inner loop)
            if num_files_to_process != -1 and seq_num > num_files_to_process:
                break

        return data

    def _generate_section_abbrev(self, section_name):
        """
        Generates a section abbreviation based on the section name.

        Args:
            section_name (str): The full name of the section.

        Returns:
            str: The abbreviated section name.
        """
        section_name_lower = section_name.lower()

        # Check for editorial
        if "editorial" in section_name_lower:
            return "EDT"

        # Check for common article types in SBIE/WIE
        if (
            "artigos completos" in section_name_lower
            or "full papers" in section_name_lower
        ):
            return "ART-C"
        if (
            "artigos resumidos" in section_name_lower
            or "short papers" in section_name_lower
        ):
            return "ART-R"

        # For workshops, try to extract the workshop acronym
        # Examples: "Workshop da Licenciatura em Computação (WLIC)" -> "WLIC"
        #           "Workshop de Ciência de Dados Educacionais (WCDE)" -> "WCDE"
        acronym_match = re.search(r"\(([A-Z][A-Z0-9-]+)\)", section_name)
        if acronym_match:
            return acronym_match.group(1)

        # If no acronym found, create one from the first letters of significant words
        # Remove common words and prepositions
        words = section_name.split()
        stop_words = {
            "da",
            "de",
            "do",
            "dos",
            "das",
            "e",
            "o",
            "a",
            "os",
            "as",
            "em",
            "para",
            "no",
            "na",
            "nos",
            "nas",
        }
        significant_words = [
            word for word in words if word.lower() not in stop_words and len(word) > 2
        ]

        if significant_words:
            # Take first letter of each significant word (up to 5 words)
            abbrev = "".join(word[0].upper() for word in significant_words[:5])
            return abbrev

        # Fallback: return first 5 characters in uppercase
        return section_name[:5].upper().replace(" ", "")

    # Convert a URL to a new URL to get the URL for metadata, according to the exemple bellow
    # Input:  http://milanesa.ime.usp.br/rbie/index.php/sbie/article/view/1114/1017
    # output: http://milanesa.ime.usp.br/rbie/index.php/sbie/rt/metadata/1114/1017
    def convert_url(self, url):
        # Replace "article/view" with "rt/metadata" in the URL
        return url.replace("article/view", "rt/metadata")

    def get_metadata(self, metadados_url):
        metadata = {
            "article": "",
            "authors": [],
            "abstractOrig": "",
            "abstractEn": "",
            "doi": "",
        }

        soup = self.download_html_and_create_parser(metadados_url)

        # Encontrar o título
        title_tag = soup.find("td", string=lambda x: x and "Título do documento" in x)
        if title_tag:
            title_td = title_tag.find_next_sibling("td")
            if title_td:
                metadata["article"] = title_td.text.strip()

        # Encontrar o DOI
        title_tag = soup.find(
            "td", string=lambda x: x and "Digital Object Identifier (DOI)" in x
        )
        if title_tag:
            title_td = title_tag.find_next_sibling("td")
            if title_td:
                metadata["doi"] = title_td.text.strip()

        author_tags = soup.find_all("td", string=lambda x: x and "Autor" in x)
        for tag in author_tags:
            # Navegar para a célula correta que contém os dados do autor
            # Se a estrutura sempre incluir uma célula de descrição antes dos dados, ajuste conforme necessário
            info_td = tag.find_next("td")  # primeiro td após o título 'Autor'
            if info_td:
                next_td = info_td.find_next_sibling("td")
                if next_td:
                    author_details = next_td.text.split(";")
                    if len(author_details) >= 3:
                        author = {
                            "name": author_details[0].strip(),
                            "authorAffiliation": author_details[1].strip(),
                            "authorCountry": author_details[2].strip(),
                        }
                        metadata["authors"].append(author)

        # Encontrar Resumo e Abstract
        description_tag = soup.find(
            "td", string=lambda x: x and ("Resumo" in x or "Abstract" in x)
        )
        if description_tag:
            next_td = description_tag.find_next_sibling("td")
            if next_td:
                content = next_td.text
                # Processar Resumo e Abstract
                if "Resumo:" in content and "Abstract:" in content:
                    # Separar Resumo e Abstract se ambos estiverem presentes
                    resumo_text = (
                        content.split("Abstract:")[0].replace("Resumo:", "").strip()
                    )
                    abstract_text = content.split("Abstract:")[1].strip()
                    metadata["abstractOrig"] = resumo_text
                    metadata["abstractEn"] = abstract_text
                elif "Resumo:" in content:
                    # Apenas Resumo presente
                    resumo_text = content.replace("Resumo:", "").strip()
                    metadata["abstractOrig"] = resumo_text
                elif "Abstract:" in content:
                    # Apenas Abstract presente
                    abstract_text = content.replace("Abstract:", "").strip()
                    metadata["abstractEn"] = abstract_text
        article = self._get_article_and_authors(metadata)
        return article

    def _get_article_and_authors(self, metadata):
        article = {
            "language": "",
            "titleOrig": metadata.get("article", ""),
            "titleEn": "",
            "abstractOrig": metadata.get("abstractOrig", ""),
            "abstractEn": metadata.get("abstractEn", ""),
            "keywordsOrig": "",
            "keywordsEn": "",
            "pages": "",
            "doi": "",
        }

        authors = []
        for i, author_metadata in enumerate(metadata.get("authors", [])):
            name_parts = author_metadata.get("name", "").split()
            author = {
                "authorFirstName": name_parts[0] if name_parts else "",
                "authorMiddleName": (
                    " ".join(name_parts[1:-1]) if len(name_parts) > 2 else ""
                ),
                "authorLastName": name_parts[-1] if len(name_parts) > 1 else "",
                "authorAffiliation": author_metadata.get("authorAffiliation", ""),
                "authorAffiliationEn": "",
                "authorCountry": author_metadata.get("authorCountry", ""),
                "authorEmail": author_metadata.get("authorEmail", ""),
                "orcid": "",
                "order": i + 1,
            }
            authors.append(author)

        article["authors"] = authors
        return article


if __name__ == "__main__":
    config_loader = ConfigLoader("config/config.json")
    config = config_loader.load()
    site_url = config["site_url"]
    # title = config['title']

    parser = OJSHTMLParser(site_url)
    articles_info = parser.extract_articles_info()

    # print(articles_info)

    # Convert the articles_info dictionary to JSON
    articles_info_json = json.dumps(articles_info)

    # Define the output file path
    output_file = "text/articles_info.json"

    # Write the JSON data to the output file
    with open(output_file, "w") as file:
        file.write(articles_info_json)

    print(f"Articles information saved to {output_file}")
