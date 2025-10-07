import os
from dotenv import load_dotenv

load_dotenv()   

class Config:
   OCR_TYPHOON_API_KEY = os.getenv("OCR_TYPHOON_API_KEY")

@classmethod
def validate_config(cls):
        """Validate required environment variables"""
        missing = []
        if not cls.OCR_TYPHOON_API_KEY:
            missing.append("OCR_TYPHOON_API_KEY")
        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")
        return True
    