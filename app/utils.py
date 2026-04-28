"""
Utility functions: retry logic, JSON parsing, etc.
"""
import json
import time
import logging

logger = logging.getLogger(__name__)


def retry_with_backoff(func, max_retries=3, delay=1):
    """Simple retry logic for external API calls with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = delay * (2 ** attempt)
            print(f"  ⚠️ Retry {attempt + 1}/{max_retries} after {wait_time}s: {e}")
            time.sleep(wait_time)


def parse_agent_json(raw_content: str) -> dict:
    """Parse JSON from agent response, handling markdown code fences."""
    cleaned = raw_content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "", 1)
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "", 1)
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())
