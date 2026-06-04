import logging
from anthropic import Anthropic
from config import Config

logger = logging.getLogger(__name__)

_client = Anthropic(api_key=Config.ANTHROPIC_API_KEY)

_SYSTEM = """\
Eres un analista de mercado forex senior con 15 años de experiencia en análisis fundamental.

Tu análisis SIEMPRE considera:
- El sentimiento global del mercado (risk-on / risk-off) como contexto
- El ciclo de política monetaria actual del banco central relevante (Fed, BCE, BoE, etc.)
- El contexto macroeconómico amplio: inflación, empleo, crecimiento, no el dato aislado
- Las expectativas del mercado antes del dato y la sorpresa vs estimados
- La correlación del dato con otros indicadores recientes

Reglas de formato:
- Responde SIEMPRE en español argentino
- Máximo 350 palabras por análisis
- Usa emojis para facilitar la lectura visual
- Sé directo y accionable
- Termina SIEMPRE con: ⚠️ Esto no es asesoramiento financiero. Operá con gestión de riesgo.
"""


def analyze_pre_event(event: dict) -> str:
    """Pre-event analysis: what to expect and how to position."""
    currency = event.get("currency", "N/A")
    title = event.get("title", "N/A")
    forecast = event.get("forecast") or "sin estimado"
    previous = event.get("previous") or "sin dato previo"

    prompt = f"""\
Próximo evento económico de alto impacto:

📊 Evento: {title}
💱 Divisa: {currency}
📈 Estimado consenso: {forecast}
⬅️ Dato anterior: {previous}

Analizá:
1. Qué mide este indicador y por qué mueve el mercado
2. Qué espera el mercado y cuál es el sesgo actual para {currency}
3. Escenario ALCISTA para {currency} (dato supera estimado)
4. Escenario BAJISTA para {currency} (dato decepciona)
5. Los pares más impactados y dirección esperada
6. Consejo operativo (gestión de riesgo incluida)
"""
    try:
        resp = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as exc:
        logger.error("Pre-event analysis failed: %s", exc)
        return "⚠️ Análisis IA no disponible en este momento."


def analyze_post_event(event: dict) -> str:
    """Post-event analysis: interpret the result with full market context."""
    currency = event.get("currency", "N/A")
    title = event.get("title", "N/A")
    actual = event.get("actual") or "no disponible"
    forecast = event.get("forecast") or "sin estimado"
    previous = event.get("previous") or "sin dato previo"

    # Determine beat/miss
    beat_str = ""
    try:
        a = float(str(actual).replace("%", "").replace("K", "000").replace("M", "000000").strip())
        f = float(str(forecast).replace("%", "").replace("K", "000").replace("M", "000000").strip())
        if a > f:
            beat_str = f"El dato SUPERÓ el estimado ({actual} vs {forecast})."
        elif a < f:
            beat_str = f"El dato DECEPCIONÓ al mercado ({actual} vs {forecast})."
        else:
            beat_str = f"El dato estuvo EN LÍNEA con el estimado ({actual})."
    except (ValueError, AttributeError):
        beat_str = f"Dato publicado: {actual} (estimado: {forecast})."

    prompt = f"""\
Resultado del evento económico de alto impacto:

📊 Evento: {title}
💱 Divisa: {currency}
🎯 Dato actual: {actual}
📈 Estimado: {forecast}
⬅️ Anterior: {previous}

{beat_str}

Analizá:
1. Evaluación del resultado (positivo / negativo / neutro para {currency}) y por qué
2. Comparación con estimados y la sorpresa implícita
3. Implicaciones para la política monetaria del banco central
4. Impacto esperado en pares de {currency} con dirección y fuerza probable
5. Sentimiento de mercado resultante y cómo encaja en el contexto macro actual
6. Qué monitorear en las próximas horas / sesión
"""
    try:
        resp = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=750,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as exc:
        logger.error("Post-event analysis failed: %s", exc)
        return "⚠️ Análisis IA no disponible en este momento."


def answer_question(question: str, events_context: str = "") -> str:
    """Answer any free-form fundamental analysis question."""
    context_block = ""
    if events_context:
        context_block = (
            f"Contexto: eventos económicos de alto impacto de hoy:\n{events_context}\n\n"
        )

    prompt = context_block + question

    try:
        resp = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as exc:
        logger.error("Q&A failed: %s", exc)
        return "⚠️ No pude procesar tu pregunta en este momento. Intentá de nuevo."
