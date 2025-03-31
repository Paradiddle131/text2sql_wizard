# Text-to-SQL Wizard

A simple web application that uses a local LLM (via Ollama) to convert natural language business queries into SQL statements, based on an introspected database schema or a provided DDL file.

## Features

*   Simple web UI with a query input box.
*   Backend powered by FastAPI.
*   Uses local LLMs via Ollama and `litellm`.
*   Generates SQL queries based on user input and database schema.
*   Dark/Light theme toggle.
*   (Planned: RAG integration, SQL execution, data visualization).

## Setup

1.  **Prerequisites:**
    *   Python 3.9+
    *   `uv` (Python package manager): [Installation Guide](https://github.com/astral-sh/uv)
    *   Ollama: [Installation Guide](https://ollama.com/)

2.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url>
    cd text2sql_wizard
    ```

3.  **Install Ollama Model:** (Example: CodeLlama 13B)
    ```bash
    ollama pull codellama:13b
    # Ensure Ollama service is running (ollama serve)
    ```

4.  **Create Virtual Environment & Install Dependencies:**
    ```bash
    uv venv
    source .venv/bin/activate  # Linux/macOS/WSL
    # or: .venv\Scripts\activate # Windows
    uv pip install -r requirements.txt
    ```

5.  **Configure Environment:**
    *   Copy `.env.example` to `.env`: `cp .env.example .env`
    *   **Crucially, edit `.env` and set your `DATABASE_URL`** (e.g., `DATABASE_URL="sqlite:///./data/db/brazilian_sales.db"`).
    *   (Optional) Override `OLLAMA_MODEL_NAME` or other settings in `.env`.

6.  **Setup Database (if using fallback or for initial creation):**
    *   Place your DDL file (containing `CREATE TABLE` statements) at `data/schema/create_tables.sql`.
    *   (If creating from CSVs) Place CSV files in `data/source_csvs/`. Run:
        ```bash
        python src/scripts/load_data.py
        ```
    *   *(The application will attempt to introspect the schema from the existing DB specified in `DATABASE_URL` first.)*

7.  **Setup Pre-commit Hooks (Optional but Recommended):**
    ```bash
    pre-commit install
    ```

## Running the Application

1.  **Ensure Ollama is running.**
2.  **Activate the virtual environment:** `source .venv/bin/activate`
3.  **Start the FastAPI server:**
    ```bash
    uvicorn main:app --reload --port 8000
    ```
4.  **Access the UI:** Open your web browser to `http://localhost:8000`.
