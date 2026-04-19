import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")
INATURALIST_API_KEY = os.getenv("INATURALIST_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
