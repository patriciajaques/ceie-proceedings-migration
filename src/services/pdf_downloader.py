import requests
from bs4 import BeautifulSoup
import os


class PDFDownloader:
    """
    A class for downloading and saving PDF files from a given base URL.

    Args:
        base_url (str): The base URL from which to retrieve the PDF files.
        save_directory (str): The directory where the downloaded PDF files will be saved.

    Methods:
        download_and_save_pdf(url): Downloads and saves a PDF file from the given URL.
        get_pdf_urls(): Retrieves the URLs of all the PDF files from the base URL.
        donwload_pdf_files_from_url(num_urls_to_process): Downloads and saves all the PDF files from the base URL.

    """

    def __init__(self, base_url, save_directory):
        self.base_url = base_url
        self.save_directory = save_directory

    def download_file(self, url):
        """
        Downloads a file from the given URL.

        Args:
            url (str): The URL of the file to download.

        Returns:
            bytes: The content of the downloaded file.

        """
        response = requests.get(url)
        response.raise_for_status()
        return response.content

    def download_and_save_pdf(self, url):
        """
        Downloads and saves a PDF file from the given URL.
        If the file already exists, skips the download.

        Args:
            url (str): The URL of the PDF file to download.

        Returns:
            str: The filepath where the PDF file is saved (or already exists).

        """
        filename = url.split("/")[-1]
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        filepath = os.path.join(self.save_directory, filename)
        if not os.path.exists(self.save_directory):
            os.makedirs(self.save_directory)

        # Check if file already exists
        if os.path.exists(filepath):
            print(f"Arquivo já existe, pulando download: {filepath}")
            return filepath

        # Download the file if it doesn't exist
        response = requests.get(url)
        response.raise_for_status()
        with open(filepath, "wb") as file:
            file.write(response.content)
        return filepath

    def get_pdf_urls(self):
        """
        Retrieves the URLs of all the PDF files from the base URL.

        Returns:
            list: A list of URLs of the PDF files.

        """
        response = requests.get(self.base_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        pdf_links = soup.find_all("a", string="PDF")
        pdf_urls = [link.get("href").replace("view", "download") for link in pdf_links]
        return pdf_urls

    def donwload_pdf_files_from_url(self, num_urls_to_process=-1):
        """
        Downloads and saves all the PDF files from the base URL.
        Skips files that already exist.

        Args:
            num_urls_to_process (int, optional): The number of PDF files to download and save.
                                                If set to -1, all the PDF files will be processed.

        """
        pdf_urls = self.get_pdf_urls()
        downloaded_count = 0
        skipped_count = 0

        # Determine total number of files to process
        total_files = (
            num_urls_to_process if num_urls_to_process != -1 else len(pdf_urls)
        )

        for i, url in enumerate(pdf_urls):
            if num_urls_to_process != -1 and i >= num_urls_to_process:
                break

            # Check if file already exists before attempting download
            filename = url.split("/")[-1]
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            filepath = os.path.join(self.save_directory, filename)
            file_exists = os.path.exists(filepath)

            if file_exists:
                print(f"[{i+1}/{total_files}] Arquivo já existe, pulando: {filename}")
                skipped_count += 1
            else:
                print(f"[{i+1}/{total_files}] Baixando PDF de {url}")
                pdf_path = self.download_and_save_pdf(url)
                print(f"Arquivo criado: {pdf_path}")
                downloaded_count += 1

        print(
            f"\nResumo: {downloaded_count} arquivo(s) baixado(s), {skipped_count} arquivo(s) já existente(s)"
        )


# Exemplo de uso
if __name__ == "__main__":
    page_url = "http://milanesa.ime.usp.br/rbie/index.php/sbie/issue/view/155"
    save_directory = "pdfs"
    pdf_downloader = PDFDownloader(page_url, save_directory)
    pdf_downloader.donwload_pdf_files_from_url(2)
