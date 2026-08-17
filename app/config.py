"""
Configuration centralisée de l'API MyGoonga.
Toutes les valeurs sont lues depuis les variables d'environnement (fichier .env en local,
variables d'environnement du service sur Render en production).
"""
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Général ---
    APP_NAME: str = "MyGoonga API"
    ENVIRONMENT: str = "development"  # development | production
    DEBUG_MODE: bool = True  # active les en-têtes X-Debug-* pour tester sans Firebase configuré
    CORS_ORIGINS: str = "*"  # liste séparée par des virgules, ou "*" pour tout autoriser

    # --- Base de données ---
    # Si USE_MOCK_DB=true (ou si aucun identifiant Firebase n'est fourni), l'API utilise
    # une base de données en mémoire. Pratique pour tester immédiatement sans configurer Firebase.
    USE_MOCK_DB: bool = True

    # --- Firebase ---
    # Chemin vers le fichier JSON du compte de service Firebase (Admin SDK), OU contenu JSON
    # directement collé dans la variable d'environnement FIREBASE_CREDENTIALS_JSON.
    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    FIREBASE_CREDENTIALS_JSON: Optional[str] = None
    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_STORAGE_BUCKET: Optional[str] = None

    # --- Stockage des fichiers ---
    STORAGE_MODE: str = "local"  # local | firebase
    LOCAL_STORAGE_DIR: str = "./storage"
    SIGNED_URL_EXPIRY_SECONDS: int = 900  # 15 minutes, pour les documents sensibles (CNI)
    SIGNED_URL_SECRET: str = "change-me-in-production"

    # --- Hugging Face ---
    HUGGINGFACE_API_TOKEN: Optional[str] = None
    HF_CLIP_MODEL: str = "openai/clip-vit-base-patch32"
    HF_WHISPER_MODEL: str = "openai/whisper-small"
    HF_SENTENCE_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    HF_TIMEOUT_SECONDS: int = 30

    # --- Google Gemini (analyse visuelle IA, facultatif) ---
    # Sans clé, l'analyse IA de l'image est désactivée proprement et le reste de
    # l'analyse (EXIF, ELA, recherche inversée) continue de fonctionner normalement.
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: int = 30
    # Plafond de sécurité, indépendant du quota réel du compte Google, pour éviter
    # toute mauvaise surprise pendant la phase de test.
    GEMINI_DAILY_IMAGE_LIMIT: int = 50

    # --- Analyse de cohérence média ---
    ELA_QUALITY: int = 90
    ELA_ANOMALY_THRESHOLD: float = 18.0  # score moyen au-delà duquel on signale une zone suspecte
    REVERSE_MATCH_SIMILARITY_THRESHOLD: float = 0.92

    # --- Scoring des événements locaux (pilier 2) ---
    FLAG_WEIGHT_VERIFIER: int = 3
    FLAG_WEIGHT_STANDARD: int = 1
    SCORE_THRESHOLD_RELIABLE: int = 5
    SCORE_THRESHOLD_DOUBTFUL: int = -5
    NEARBY_DEFAULT_RADIUS_KM: float = 1500.0

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
