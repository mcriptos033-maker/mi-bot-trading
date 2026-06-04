import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

    # UTC-3 — hora de Argentina (fijo)
    TIMEZONE: str = "America/Argentina/Buenos_Aires"
    MORNING_HOUR: int = 7    # primer reporte cada día a las 07:00
    MORNING_MINUTE: int = 0
    PRE_NEWS_MINUTES: int = 7   # alerta 7 min antes de cada noticia
    POST_EVENT_DELAY_MIN: int = 12  # análisis 12 min después del dato
