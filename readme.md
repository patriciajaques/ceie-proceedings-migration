# Academic Metadata Migration Tool

## Authorship

This tool was created by Patricia Jaques Maillard (patricia[dot]jaques[at]gmail[dot]com) while serving as the coordinator of the Special Commission on Informatics in Education (CEIE) of the Brazilian Computer Society (SBC) during 2024-2025.

The project was developed to facilitate the migration of proceedings from the Brazilian Symposium on Computers in Education (SBIE) and the Workshop on Informatics in Education (WIE) from an outdated Open Journal System (OJS) to the SBC SOL server or to a dedicated website. These proceedings are under the responsibility of CEIE, and this migration tool helps preserve and make accessible important academic content in the field of educational informatics in Brazil.

## Overview

This project is an automated tool for extracting and processing academic article metadata from PDF files and web sources. It's designed for the CEIE (Brazilian Commission for Computer Science Education) to help migrate article metadata from conference proceedings and journals to a structured database.

The system performs the following high-level tasks:
1. Download PDF files from academic websites
2. Extract text content from PDFs
3. Parse HTML pages for basic article metadata
4. Use AI to extract comprehensive article metadata from PDF text
5. Correct and complete missing information
6. Generate standardized CSV files for articles, authors, and references

## Project Structure

```
migracao-refatorado/
├── config/
│   ├── config.json             # Main configuration file
│   ├── headers.json            # CSV header definitions
│   └── prompts.yaml            # AI prompts for different extraction tasks
└── src/
    ├── adapters/               # AI service adapters
    ├── config/                 # Configuration management
    ├── domain/                 # Domain model classes
    ├── io/                     # Input/output operations
    ├── logging/                # Logging utilities
    ├── services/               # Core business logic
    ├── utils/                  # Utility functions
    └── main.py                 # Application entry point
```

## Key Components

### Domain Model

The domain model consists of three main entities:

1. **Article**: Represents an academic article with its metadata (titles, abstracts, keywords, etc.)
2. **Author**: Represents an article author with personal and institutional information
3. **Reference**: Represents a bibliographic reference cited in an article

All domain classes inherit from `BaseModel`, which provides common functionality for converting between dictionaries and domain objects.

### Service Layer

The service layer contains the core business logic:

- **Migrator**: Orchestrates the entire migration process
- **ArticleExtractor**: Extracts structured metadata from text using AI
- **PDFDownloader**: Downloads PDF files from academic websites
- **PDFProcessor**: Extracts text from PDF files
- **OJSHTMLParser**: Parses HTML pages from the Open Journal System (OJS)
- **AuthorsAffiliationCorrector**: Corrects and standardizes author affiliations

### AI Adapters

The system can use multiple AI services through a consistent interface:

- **OpenAIClient**: Client for OpenAI's GPT services
- **AnthropicClient**: Client for Anthropic's Claude services

Both clients implement the `AIClientInterface` and inherit from `BaseAIClient`.

### Configuration Management

The application uses a robust configuration system:

- **ConfigLoader**: Loads configuration from JSON files
- **CredentialsManagerInterface**: Abstract interface for credential management
- **AnthropicCredentialsManager** and **OpenAICredentialsManager**: Manage API credentials

### Utilities

- **TextProcessor**: Cleans and processes text, correcting encoding issues
- **JsonLogger**: Logs data structures in JSON format for debugging and auditing

## How It Works

### Workflow

1. **Initialization**: The application reads configuration from `config.json` and sets up all components
2. **PDF Download**: The system downloads PDF files from the specified OJS website
3. **Text Extraction**: The PDFProcessor extracts text from the PDFs
4. **Metadata Extraction**: Two parallel processes extract metadata:
   - HTML parsing to get basic article information (title, section, page numbers)
   - AI-based extraction to get detailed article data (abstracts, authors, references)
5. **Data Merging**: Information from both sources is merged into a unified article model
6. **Completion**: AI is used to fill in any missing fields
7. **Affiliation Correction**: Author affiliations are standardized and translated
8. **Output Generation**: Three CSV files are produced:
   - Articles.csv: Article metadata
   - Autores.csv: Author information
   - Referencias.csv: Bibliographic references

### AI Processing

The system uses AI for three main tasks:

1. **Article Metadata Extraction**: Extracts titles, abstracts, keywords from first pages
2. **References Extraction**: Extracts bibliography from the last pages
3. **Field Completion**: Fills in missing data and translates content when needed

## Configuration

### Main Configuration (config.json)

Key configuration options:

- `site_url`: URL of the OJS website to process
- `year`: Publication year of the conference/journal
- `engine`: The OpenAI model to use
- `anthropic_model`: The Anthropic model to use
- `output_dir`: Directory for output files
- `doi_prefix`: DOI prefix for the publication
- `pages_to_process`: Number of pages to process per PDF
- `files_to_download`: Number of files to download (-1 for all)

### Environment Variables (.env file)

The application requires a `.env` file in the root directory with the following environment variables:

```
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
USE_OPENAI=true
```

These variables are used for:

- `OPENAI_API_KEY`: OpenAI API key for GPT models
- `ANTHROPIC_API_KEY`: Anthropic API key for Claude models
- `USE_OPENAI`: Flag to choose between OpenAI or Anthropic (true/false)

## Output

The system generates three CSV files:

1. **Artigos.csv**: Contains article metadata (titles, abstracts, keywords, etc.)
2. **Autores.csv**: Contains author information (names, affiliations, countries, etc.)
3. **Referencias.csv**: Contains bibliographic references

## Usage

### Running the Migration

To run the migration process:

```bash
python src/main.py
```

The program will:
1. Clear the terminal screen
2. Load configuration and environment variables
3. Create AI clients as configured
4. Initialize the article extractor and migrator
5. Execute the migration process
6. Generate CSV files in the configured output directory

## Implementation Details

### AI Client Factory

The application uses a factory function to create multiple AI clients with different prompts:

```python
def create_ai_clients(config_loader: ConfigLoader, use_openai: bool) -> Dict[str, AIClientInterface]:
    client_class = OpenAIClient if use_openai else AnthropicClient
    
    client_types = {
        "article_ai_client": "article_extraction",
        "references_ai_client": "references_extraction",
        "field_completion_ai_client": "field_completion",
        "affiliation_correction_client": "author_affiliation_correction",
        "text_processing_client": "text_processing"
    }
    
    return {
        client_key: client_class(config_loader, prompt_key)
        for client_key, prompt_key in client_types.items()
    }
```

### Text Processing

The `TextProcessor` class provides methods for cleaning text and fixing encoding errors:

```python
def clean_text(self, text):
    if not text:
        return ""

    if self.detect_encoding_errors(text):
        return self.process_with_ai(text)

    return self.basic_cleaning(text)
```

### Affiliation Correction

The system uses AI to correct and standardize author affiliations:

```python
def correct_affiliation_columns_from_authors_csv(self):
    authors_df = self.load_authors_data()
    authors_aff_df = authors_df[["authorAffiliation", "authorAffiliationEn"]]
    chunks = self.split_into_chunks(authors_aff_df)
    
    dict_list = []
    for chunk in chunks:
        result = self.process_affiliation_chunk(chunk)
        dict_list.extend(result)
    
    authors_df = self.merge_and_update_dataframe(authors_df, dict_list)
    self.save_corrected_data(authors_df)
    
    return self.convert_to_domain_objects(authors_df)
```

## Dependencies

- **OpenAI**: API client for GPT models
- **Anthropic**: API client for Claude models
- **PyPDF**: PDF processing
- **PyMuPDF**: Text extraction from PDFs
- **BeautifulSoup**: HTML parsing
- **pandas**: Data manipulation
- **numpy**: Numerical processing
- **python-dotenv**: Environment variable management
- **PyYAML**: YAML file parsing

## Design Principles

The codebase follows several key design principles:

1. **DRY (Don't Repeat Yourself)**: Common functionality is centralized
2. **KISS (Keep It Simple, Stupid)**: Simple solutions are preferred over complex ones
3. **SOLID**:
   - **Single Responsibility**: Each class has a specific purpose
   - **Open/Closed**: Classes are open for extension but closed for modification
   - **Liskov Substitution**: Derived classes (like AI clients) can be used in place of base classes
   - **Interface Segregation**: Clean interfaces with minimal methods
   - **Dependency Inversion**: High-level modules depend on abstractions

## Extension Points

The system can be extended in several ways:

1. **New AI Providers**: Create a new class implementing `AIClientInterface`
2. **Additional Data Sources**: Add new parsers in the services directory
3. **Enhanced Domain Model**: Extend the domain classes with additional fields
4. **Custom Text Processing**: Modify the TextProcessor class or provide alternatives
5. **Output Formats**: Add new writers in the io directory