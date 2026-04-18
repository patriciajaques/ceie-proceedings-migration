from bs4 import BeautifulSoup
from src.services.pdf_downloader import PDFDownloader
from src.config.config_loader import ConfigLoader
import json
import re
import os
from urllib.parse import urlparse, unquote


class OJSHTMLParser:
    def __init__(self, site_url, siglas_mapping_path=None):
        self.site_url = site_url
        self.siglas_mapping_path = siglas_mapping_path or "config/section_siglas.json"
        self._siglas_mappings = None

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
        - Title, authors, abstracts, DOI, and page fields from each article's
          ``rt/metadata`` page when a PDF link exists (TOC values are fallbacks)
        - The starting page from the TOC when metadata does not provide it

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
        seen_abbrevs = {}  # Map to track how many times we've seen each abbreviation

        for section in sections:
            section_name = section.text.strip()
            # Generate section abbreviation based on the section name
            base_section_abbrev = self._generate_section_abbrev(section_name)
            # Make abbreviation unique if it's already been used
            section_abbrev = self._make_abbrev_unique(base_section_abbrev, seen_abbrevs)

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

                print("Processando arquivo: ", pdf_file_name)

                # Milanesa rt/metadata page is authoritative for title, authors,
                # abstracts, DOI, and page fields; TOC values are fallbacks only.
                if pdf_link_element:
                    additional_metadata = self.get_metadata(metadados_url)
                    print(
                        "Pegou metadados adicionais: do arquivo",
                        pdf_file_name,
                    )
                else:
                    additional_metadata = self._get_article_and_authors(
                        {
                            "article": article_title,
                            "authors": [],
                            "abstractOrig": "",
                            "abstractEn": "",
                            "doi": "",
                            "pages_range": "",
                            "first_page_cell": page_start,
                        }
                    )

                merged = dict(additional_metadata)
                merged["seq"] = seq_num
                merged["sectionAbbrev"] = section_abbrev
                merged["idJEMS"] = pdf_file_name
                if not (merged.get("titleOrig") or "").strip():
                    merged["titleOrig"] = article_title
                if not (merged.get("firstPage") or "").strip():
                    merged["firstPage"] = page_start
                if "authors" not in merged:
                    merged["authors"] = []
                data.append(merged)

                seq_num += 1
                next_sibling = next_sibling.find_next_sibling()

            # Check if we've reached the limit (outside the inner loop)
            if num_files_to_process != -1 and seq_num > num_files_to_process:
                break

        return data

    def extract_sections_from_website(self):
        """
        Extracts sections information from the HTML file.

        Returns:
            list: A list of dictionaries containing section information with the following keys:
                - sectionTitle: Section name in Portuguese
                - sectionTitleEn: Section name in English (same as Portuguese if not available)
                - sectionAbbrev: Section abbreviation (guaranteed unique)
                - blind, numSubmitted, numAccepted, dateSub, dateResult, dateReady: Empty fields
        """
        soup = self.download_html_and_create_parser(self.site_url)

        # Identify all sections using the same method as extract_articles_info_from_the_website
        sections = soup.find_all("h4", class_="tocSectionTitle")

        sections_data = []
        seen_abbrevs = {}  # Map to track how many times we've seen each abbreviation

        for section in sections:
            section_name = section.text.strip()
            base_section_abbrev = self._generate_section_abbrev(section_name)

            # Make abbreviation unique if it's already been used
            section_abbrev = self._make_abbrev_unique(base_section_abbrev, seen_abbrevs)

            section_data = {
                "sectionTitle": section_name,
                "sectionTitleEn": section_name,  # Using same text as Portuguese for now
                "sectionAbbrev": section_abbrev,
                "blind": "",
                "numSubmitted": "",
                "numAccepted": "",
                "dateSub": "",
                "dateResult": "",
                "dateReady": "",
            }
            sections_data.append(section_data)

            # Warn if abbreviation had to be modified
            if section_abbrev != base_section_abbrev:
                print(
                    f"AVISO: Sigla duplicada detectada! "
                    f"Sessão '{section_name}' recebeu sigla única: {section_abbrev} "
                    f"(original: {base_section_abbrev})"
                )

        return sections_data

    def _make_abbrev_unique(self, base_abbrev, seen_abbrevs):
        """
        Makes an abbreviation unique by adding a numeric suffix if necessary.

        Args:
            base_abbrev (str): The base abbreviation.
            seen_abbrevs (dict): Dictionary tracking how many times each abbreviation has been seen.

        Returns:
            str: A unique abbreviation.
        """
        if base_abbrev not in seen_abbrevs:
            seen_abbrevs[base_abbrev] = 0
            return base_abbrev
        else:
            seen_abbrevs[base_abbrev] += 1
            return f"{base_abbrev}-{seen_abbrevs[base_abbrev]}"

    def _load_siglas_mappings(self):
        """
        Loads the section siglas mapping from JSON file (lazy loading).

        Returns:
            list: List of mapping configurations, or empty list if file doesn't exist.
        """
        if self._siglas_mappings is not None:
            return self._siglas_mappings

        if not os.path.exists(self.siglas_mapping_path):
            self._siglas_mappings = []
            return []

        try:
            with open(self.siglas_mapping_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Sort by priority (higher priority first - lower number = higher priority)
                mappings = config.get("mappings", [])
                mappings.sort(key=lambda x: x.get("priority", 999), reverse=False)
                self._siglas_mappings = mappings
                return self._siglas_mappings
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            print(f"AVISO: Erro ao carregar mapeamento de siglas: {e}")
            self._siglas_mappings = []
            return []

    def _check_sigla_mapping(self, section_name):
        """
        Checks if a section name matches any mapping configuration.

        Args:
            section_name (str): The full name of the section.

        Returns:
            str or None: The mapped sigla if a match is found, None otherwise.
        """
        section_name_lower = section_name.lower()
        mappings = self._load_siglas_mappings()

        for mapping in mappings:
            if mapping.get("type") != "keywords":
                continue

            match_config = mapping.get("match", {})
            all_keywords = match_config.get("all_keywords", [])
            any_keywords = match_config.get("any_keywords", [])

            # Check if all required keywords are present
            if all_keywords:
                if not all(
                    keyword.lower() in section_name_lower for keyword in all_keywords
                ):
                    continue

            # Check if at least one of the optional keywords is present
            if any_keywords:
                if not any(
                    keyword.lower() in section_name_lower for keyword in any_keywords
                ):
                    continue

            # Match found! Now determine suffix
            base_sigla = mapping.get("base_sigla", "")
            suffixes = mapping.get("suffixes", [])

            suffix = ""
            for suffix_config in suffixes:
                suffix_keywords = suffix_config.get("keywords", [])
                if any(
                    keyword.lower() in section_name_lower for keyword in suffix_keywords
                ):
                    suffix = suffix_config.get("suffix", "")
                    break

            return f"{base_sigla}{suffix}" if suffix else base_sigla

        return None

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

    def _generate_section_abbrev(self, section_name):
        """
        Generates a section abbreviation based on the section name.
        First checks custom mappings, then falls back to automatic generation.

        Args:
            section_name (str): The full name of the section.

        Returns:
            str: The abbreviated section name.
        """
        # Check custom mappings first
        mapped_sigla = self._check_sigla_mapping(section_name)
        if mapped_sigla:
            return mapped_sigla

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
        # Milanesa often labels full papers as "Artigos (Papers)" without "completos"
        if (
            "artigos" in section_name_lower
            and "papers" in section_name_lower
            and "short" not in section_name_lower
            and "resumid" not in section_name_lower
        ):
            return "ART-C"

        # For workshops, try to extract the workshop acronym
        # Examples: "Workshop da Licenciatura em Computação (WLIC)" -> "WLIC"
        #           "Workshop de Ciência de Dados Educacionais (WCDE)" -> "WCDE"
        acronym_match = re.search(r"\(([A-Z][A-Z0-9-]+)\)", section_name)
        if acronym_match:
            return acronym_match.group(1)

        # If no acronym found, create one from the first letters of significant words
        # Drop parenthetical text so "(Papers)" does not yield "(" as an initial
        section_for_words = re.sub(r"\([^)]*\)", " ", section_name)
        words = section_for_words.split()
        # Remove common words and prepositions
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

    @staticmethod
    def _metadata_table_field(soup, label_needles: tuple[str, ...]) -> str:
        """
        Read the value cell next to a label ``td`` on OJS rt/metadata HTML tables.

        Args:
            soup: Parsed metadata page.
            label_needles: Substrings to match label cells (e.g. \"Páginas\").
        """
        for needle in label_needles:
            needle_lower = needle.lower()
            for td in soup.find_all("td"):
                label_text = td.get_text(separator=" ", strip=True) or ""
                if needle_lower in label_text.lower():
                    sib = td.find_next_sibling("td")
                    if sib is not None:
                        return sib.get_text(separator=" ", strip=True)
        return ""

    @staticmethod
    def _normalize_language_from_metadata(raw: str) -> str:
        """
        Map OJS metadata language labels to a 2-letter code (pt, en, es) or "".

        PKP often stores full names (e.g. \"Portuguese\", \"English\") or locale
        codes (pt_BR, en_US). Field completion expects pt/en/es elsewhere.
        """
        if not raw or not str(raw).strip():
            return ""
        s = str(raw).strip()
        low = s.lower().replace("_", "-")
        # Locale-style: pt-br, en-us, es-es
        head = low.split("-")[0].strip()
        if len(head) == 2 and head in ("pt", "en", "es"):
            return head
        # 3-letter ISO 639-2 common in OJS
        if head in ("por", "pt"):
            return "pt"
        if head in ("eng", "en"):
            return "en"
        if head in ("spa", "es"):
            return "es"
        # Full names (EN/PT/ES UI)
        if "portug" in low or "portugu" in low or "brazil" in low:
            return "pt"
        if (
            "english" in low
            or "inglês" in low
            or "ingles" in low
            or low.strip() == "en"
            or "anglais" in low
        ):
            return "en"
        if "spanish" in low or "españ" in low or "espanho" in low or "castel" in low:
            return "es"
        # Single word short forms sometimes seen in tables
        if low in ("portuguese", "português", "portugues"):
            return "pt"
        if low in ("english", "inglês", "ingles"):
            return "en"
        if low in ("spanish", "espanhol", "español"):
            return "es"
        return ""

    @staticmethod
    def _first_page_from_pages_range(pages_range: str) -> str:
        """Return leading page number from strings like \"1-10\" or \"12–15\"."""
        if not pages_range or not str(pages_range).strip():
            return ""
        normalized = (
            str(pages_range)
            .strip()
            .replace("–", "-")
            .replace("—", "-")
        )
        m = re.match(r"^\s*(\d+)", normalized)
        return m.group(1) if m else ""

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
                doi_value = title_td.text.strip()
                # Normalize DOI to store only the identifier (remove URL prefix)
                metadata["doi"] = self._normalize_doi(doi_value)

        # Match label cell exactly "Autor" (not "Direito autoral", etc.)
        author_tags = soup.find_all(
            "td",
            string=lambda x: x is not None and x.strip() == "Autor",
        )
        for tag in author_tags:
            # PKP table: ... | Autor | hint column | value column |
            info_td = tag.find_next("td")
            if info_td:
                next_td = info_td.find_next_sibling("td")
                if next_td:
                    raw = next_td.get_text(separator=" ", strip=True)
                    parts = [p.strip() for p in raw.split(";") if p.strip()]
                    if not parts:
                        continue
                    if len(parts) >= 3:
                        author = {
                            "name": parts[0],
                            "authorAffiliation": parts[1],
                            "authorCountry": parts[2],
                            "authorEmail": (
                                parts[3] if len(parts) >= 4 and parts[3] else ""
                            ),
                        }
                    elif len(parts) == 2:
                        author = {
                            "name": parts[0],
                            "authorAffiliation": parts[1],
                            "authorCountry": "",
                            "authorEmail": "",
                        }
                    else:
                        # Milanesa SBIE: often only the full name in the value cell
                        author = {
                            "name": parts[0],
                            "authorAffiliation": "",
                            "authorCountry": "",
                            "authorEmail": "",
                        }
                    metadata["authors"].append(author)

        # Fallback: procurar linhas "E-mail" / "Email" na tabela (comum em OJS)
        # e preencher por ordem (primeiro e-mail -> primeiro autor, etc.)
        if metadata["authors"] and not any(
            a.get("authorEmail") for a in metadata["authors"]
        ):
            email_tags = soup.find_all(
                "td",
                string=lambda x: x
                and ("E-mail" in (x.strip()) or "Email" in (x.strip())),
            )
            emails_from_rows = []
            for et in email_tags:
                next_td = et.find_next_sibling("td")
                if next_td:
                    val = next_td.text.strip()
                    if val and "@" in val:
                        emails_from_rows.append(val)
            for i, author in enumerate(metadata["authors"]):
                if i < len(emails_from_rows):
                    author["authorEmail"] = emails_from_rows[i]

        # Resumo / Abstract: PKP uses a row like | Descrição | Resumo | <body text>
        # without "Resumo:" inside the body cell (Milanesa SBIE 2012). Older code only
        # filled abstracts when those prefixes appeared in the same cell.
        for label_td in soup.find_all("td"):
            label = label_td.get_text(strip=True)
            if label not in ("Resumo", "Abstract"):
                continue
            val_td = label_td.find_next_sibling("td")
            if not val_td:
                continue
            content = val_td.get_text(separator=" ", strip=True)
            if not content:
                continue
            if "Resumo:" in content and "Abstract:" in content:
                resumo_text = (
                    content.split("Abstract:")[0].replace("Resumo:", "").strip()
                )
                abstract_text = content.split("Abstract:")[1].strip()
                metadata["abstractOrig"] = resumo_text
                metadata["abstractEn"] = abstract_text
            elif "Resumo:" in content:
                metadata["abstractOrig"] = content.replace("Resumo:", "").strip()
            elif "Abstract:" in content:
                metadata["abstractEn"] = content.replace("Abstract:", "").strip()
            elif label == "Resumo":
                metadata["abstractOrig"] = content
            elif label == "Abstract":
                metadata["abstractEn"] = content

        metadata["pages_range"] = self._metadata_table_field(
            soup,
            ("Páginas", "Pages", "Page range"),
        )
        metadata["first_page_cell"] = self._metadata_table_field(
            soup,
            (
                "Primeira página",
                "First page",
                "Starting page",
                "First Page",
            ),
        )
        lang_raw = self._metadata_table_field(
            soup,
            (
                "Language",
                "Idioma",
                "Língua",
                "Lingua",
                "Submission language",
                "Idioma da submissão",
                "Primary language",
                "Idioma principal",
            ),
        )
        metadata["language"] = self._normalize_language_from_metadata(lang_raw)
        article = self._get_article_and_authors(metadata)
        return article

    def _get_article_and_authors(self, metadata):
        pages_val = (metadata.get("pages_range") or "").strip()
        first_page_val = (metadata.get("first_page_cell") or "").strip()
        if not first_page_val and pages_val:
            first_page_val = self._first_page_from_pages_range(pages_val)

        lang = self._normalize_language_from_metadata(metadata.get("language") or "")
        article = {
            "language": lang,
            "titleOrig": metadata.get("article", ""),
            "titleEn": "",
            "abstractOrig": metadata.get("abstractOrig", ""),
            "abstractEn": metadata.get("abstractEn", ""),
            "keywordsOrig": "",
            "keywordsEn": "",
            "firstPage": first_page_val,
            "pages": pages_val,
            "doi": metadata.get("doi", ""),  # Preserve DOI extracted from website
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
    site_url = config_loader.get_config_value("site_url")

    parser = OJSHTMLParser(site_url)
    articles_info = parser.extract_articles_info_from_the_website(-1)

    output_file = "temp/articles_info.json"
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(json.dumps(articles_info, ensure_ascii=False, indent=2))

    print(f"Articles information saved to {output_file}")
