import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    TIMEZONE: str = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")
    MORNING_HOUR: int = int(os.getenv("MORNING_HOUR", "7"))
    MORNING_MINUTE: int = int(os.getenv("MORNING_MINUTE", "0"))
    PRE_NEWS_MINUTES: int = int(os.getenv("PRE_NEWS_MINUTES", "7"))
    POST_EVENT_DELAY_MIN: int = int(os.getenv("POST_EVENT_DELAY_MIN", "12"))
