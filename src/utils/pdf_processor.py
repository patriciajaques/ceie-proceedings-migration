import os
import json
from pdfminer.high_level import extract_text_to_fp
from io import BytesIO


class PDFProcessor:
    """
    A class for processing PDF files. Processing here means extracting text from PDF files in a directory.
    """

    def __init__(self, directory):
        """
        Initialize the PDFProcessor class.

        Args:
            directory (str): The directory where the PDF files are located.
        """
        self.directory = directory

    def extract_text_from_each_page_using_pdfminer(self, pdf_path):
        """
        Extract text from each page of a PDF file using pdfminer.

        Args:
            pdf_path (str): The full path of the PDF file.

        Returns:
            tuple: A tuple containing a list of texts, where each position in the list contains the text of a page
                  of the PDF, and the total number of pages in the PDF.
        """
        with open(pdf_path, "rb") as file:
            output = BytesIO()
            extract_text_to_fp(file, output)
            text = output.getvalue().decode()
            text_pages = text.split("\x0c")
            if text_pages[-1] == "":
                text_pages = text_pages[
                    :-1
                ]  # remove the last element if it's an empty string
            total_pages = len(text_pages)
            return text_pages, total_pages

    def process_all_pdfs(self, save_files=False, number_of_pages_to_process=1):
        """
        Process all PDF files in the specified directory.

        Args:
            save_files (bool, optional): Indicates whether text files should be saved. Default is False.
            number_of_pages_to_process (int, optional): The number of pages to process in each PDF. Default is 1.
                If -1, processes all pages. Otherwise, limits to the specified number of pages.

        Returns:
            list: A list containing the data of all processed PDF files. Each item in the list is a dictionary
                 with the following keys:
                - 'text': The text extracted from the PDF.
                - 'numPages': The number of pages in the file.
                - 'base_filename': The filename without the extension.
        """
        allFilesData = []
        for filename in os.listdir(self.directory):
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(self.directory, filename)
                text_pages, numPages = self.extract_text_from_each_page_using_pdfminer(
                    pdf_path
                )

                # Limit the number of pages to process if specified
                original_num_pages = numPages
                if number_of_pages_to_process != -1 and number_of_pages_to_process > 0:
                    # Process only the first N pages
                    text_pages = text_pages[:number_of_pages_to_process]
                    # Update numPages to reflect the actual number of pages processed
                    numPages = min(original_num_pages, number_of_pages_to_process)

                # Separate the filename from its extension
                base_filename = os.path.splitext(filename)[0]
                fileData = {
                    "text_pages": text_pages,
                    "numPages": numPages,
                    "base_filename": base_filename,
                }
                allFilesData.append(fileData)
                if save_files:
                    # Save the dictionary to a .json file
                    os.makedirs("outputs/text", exist_ok=True)
                    with open("outputs/text/" + base_filename + ".json", "w") as f:
                        json.dump(fileData, f)
        return allFilesData


# Example usage
if __name__ == "__main__":
    save_directory = "pdfs"
    pdf_processor = PDFProcessor(save_directory)
    allFilesText = pdf_processor.process_all_pdfs()

    print(allFilesText)
