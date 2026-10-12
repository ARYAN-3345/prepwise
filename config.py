import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///gate_tracker.db")
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql+psycopg://", 1)
    elif SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgresql://", "postgresql+psycopg://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Neon may close idle pooled connections; verify them before reuse and
    # recycle connections periodically so requests reconnect cleanly.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300}
    # Leave a little room for multipart form overhead beyond the 100 MB file cap.
    MAX_CONTENT_LENGTH = 105 * 1024 * 1024
    UPLOAD_FOLDER = Path(__file__).parent / "instance" / "uploads"
    S3_BUCKET = os.getenv("S3_BUCKET", "")
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
    AWS_REGION = os.getenv("AWS_REGION", "auto")
