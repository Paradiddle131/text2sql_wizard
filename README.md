# Text-to-SQL Wizard

A simple web application that uses a local LLM (via Ollama) to convert natural language business queries into SQL statements, based on introspection of a connected PostgreSQL database schema.

## Features

*   Simple web UI with a query input box.
*   Backend powered by FastAPI.
*   Uses local LLMs via Ollama and `litellm`.
*   Generates PostgreSQL queries based on user input and introspected database schema.
*   Dark/Light theme toggle.
*   (Planned: RAG integration, SQL execution, data visualization).

## Setup

1.  **Prerequisites:**
    *   Python 3.9+
    *   `uv`: [Installation Guide](https://github.com/astral-sh/uv)
    *   Ollama: [Installation Guide](https://ollama.com/)
    *   **PostgreSQL Server:** A running PostgreSQL instance with your database and schema already created and populated.

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
    *   **Edit `.env` and set your PostgreSQL connection details** (either `DATABASE_URL` or `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`).
    *   Ensure the specified `DB_USER` has `CONNECT` privileges on the database and `SELECT` privileges on the tables within the `DB_SCHEMA` (default `public`) that you want the application to see. The user also needs usage rights on the schema itself (`GRANT USAGE ON SCHEMA your_schema TO your_user;`).
    *   (Optional) Override other settings like `OLLAMA_MODEL_NAME`, `DB_SCHEMA` in `.env`.

6.  **Database Preparation:**
    *   **This application reads from an existing database.** Ensure your PostgreSQL database, schema (`public` by default, or set `DB_SCHEMA` in `.env`), tables, and data are already set up *before* running the application.

7.  **Setup Pre-commit Hooks (Optional but Recommended):**
    ```bash
    pre-commit install
    ```

## Running the Application

1.  **Ensure Ollama and PostgreSQL are running.**
2.  **Activate the virtual environment:** `source .venv/bin/activate`
3.  **Start the FastAPI server:**
    ```bash
    uvicorn main:app --reload --port 8000
    ```
4.  **Access the UI:** Open your web browser to `http://localhost:8000`.
