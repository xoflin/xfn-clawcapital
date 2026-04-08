"""
Skill: sentiment/gemini_sentiment
Analyses crypto market sentiment from news headlines using Gemini Flash.

Input:  gemini_api_key (str), headlines (list[dict])
Output: dict with sentiment, confidence, key_drivers, summary,
        top_assets_mentioned, risk_events
"""

import json
import re

import google.generativeai as genai


SENTIMENT_PROMPT = """
You are an experienced crypto market analyst. Based on the following news headlines,
analyse the overall market sentiment.

Headlines (JSON):
{headlines_json}

Respond EXCLUSIVELY in the following JSON format, with no additional text:
{{
  "sentiment": "<Strongly Bullish | Bullish | Neutral | Bearish | Strongly Bearish>",
  "confidence": <number from 0.0 to 1.0>,
  "key_drivers": ["<driver 1>", "<driver 2>", "<driver 3>"],
  "summary": "<2-sentence summary>",
  "top_assets_mentioned": ["<ticker1>", "<ticker2>"],
  "risk_events": ["<critical event if any, otherwise empty list>"]
}}
"""

VALID_SENTIMENTS = {
    "Strongly Bullish",
    "Bullish",
    "Neutral",
    "Bearish",
    "Strongly Bearish",
}


def analyse(api_key: str, headlines: list[dict]) -> dict:
    """
    Analyses market sentiment from a list of news headlines.

    Args:
        api_key:   Google Gemini API key.
        headlines: List of dicts with a "title" field (and optionally others).

    Returns:
        Dict with fields: sentiment, confidence, key_drivers, summary,
        top_assets_mentioned, risk_events.

    Raises:
        json.JSONDecodeError: If Gemini does not return valid JSON.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    headlines_json_str = json.dumps(headlines, ensure_ascii=False, indent=2)
    prompt = SENTIMENT_PROMPT.format(headlines_json=headlines_json_str)

    response = model.generate_content(prompt)
    raw_text = response.text.strip()

    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    result = json.loads(raw_text)

    if result.get("sentiment") not in VALID_SENTIMENTS:
        result["sentiment"] = "Neutral"

    return result
