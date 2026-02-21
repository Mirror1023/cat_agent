import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images" / "local"
HISTORY_DIR = BASE_DIR / "images" / "history"
DATA_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    
    # Database
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR / 'catgram.db'}"
    
    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    
    # OpenAI (optional — for DALL-E)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    
    # Instagram Platform API (Instagram Login — no Facebook Page required)
    INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
    INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
    GRAPH_API_VERSION = "v21.0"
    # Key change: use graph.instagram.com instead of graph.facebook.com
    GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
    
    # Admin
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
    
    # Agent defaults
    IMAGE_SOURCE = os.getenv("IMAGE_SOURCE", "random")
    POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "8"))
    ENABLE_COMMENT_REPLIES = os.getenv("ENABLE_COMMENT_REPLIES", "true").lower() == "true"
    MAX_POSTS_PER_DAY = int(os.getenv("MAX_POSTS_PER_DAY", "3"))
    AGENT_PERSONA = os.getenv(
        "AGENT_PERSONA",
        "You are a playful, witty cat lover who runs a fun Instagram account about cats. "
        "Use cat puns, emojis, and a warm friendly tone."
    )
    
    # Version
    APP_VERSION = "1.2.4"
    APP_VERSION_DATE = "Feb 21, 2026 · 3:52 PM EST"

    # Rate limits
    MIN_POST_GAP_MINUTES = 50
    MAX_COMMENT_REPLIES_PER_HOUR = 30
    
    # Image settings
    LOCAL_IMAGES_DIR = str(IMAGES_DIR)
