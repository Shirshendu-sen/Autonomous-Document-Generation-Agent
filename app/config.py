"""
app/config.py
--------------
Centralised configuration, loaded from environment variables (.env supported).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # loads a local .env file if present, otherwise a no-op

# ---- LLM provider selection -------------------------------------------------
# "groq"  -> uses Groq's free-tier hosted API (fast Llama/Mixtral models)
# "ollama"-> uses a locally running Ollama server (fully offline / free)
# "mock"  -> deterministic offline stub, used automatically as a fallback
#            when no provider is configured/reachable, and great for CI/demo.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# ---- Agent behaviour ---------------------------------------------------------
MAX_REFLECTION_ROUNDS = int(os.getenv("MAX_REFLECTION_ROUNDS", "2"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

MIN_REQUEST_LENGTH = 8
MAX_REQUEST_LENGTH = 4000

# ---- Storage ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "generated_docs"
OUTPUT_DIR.mkdir(exist_ok=True)
