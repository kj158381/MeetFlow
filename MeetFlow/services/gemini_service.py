"""
services/gemini_service.py
Gemini AI integration: key-point extraction, AI summary, translation.
"""
import re, json, logging, requests
logger = logging.getLogger(__name__)

# ── Key-point extraction ──────────────────────────────────────────────────────

def extract_key_points(transcript: str, api_key: str) -> dict:
    """
    Send meeting transcript to Gemini and return structured key points + summary.
    Falls back to smart keyword extraction if Gemini is unavailable.
    """
    if not transcript:
        return {"key_points": [], "summary": "", "word_count": 0, "ai_powered": False}

    wc = len(transcript.split())

    if api_key:
        try:
            prompt = f"""You are a professional meeting analyst. Analyze the following meeting transcript.

Transcript ({wc} words):
{transcript[:6000]}

Return ONLY a valid JSON object — no markdown, no code fences, no extra text:
{{
  "key_points": [
    {{"type": "decision",  "text": "A specific decision made",         "timestamp": ""}},
    {{"type": "action",    "text": "An action item assigned to someone","timestamp": ""}},
    {{"type": "deadline",  "text": "A deadline or time-sensitive item", "timestamp": ""}},
    {{"type": "follow_up", "text": "Something to revisit later",       "timestamp": ""}}
  ],
  "summary": "2-3 sentence executive summary of the meeting.",
  "word_count": {wc}
}}

Rules:
- Extract 3–8 key points total
- Each text must be a complete self-contained sentence (≥10 words)
- Types: decision=conclusions, action=tasks assigned, deadline=time items, follow_up=topics to revisit
- Summary must describe THIS specific meeting content
- Do NOT include placeholder or generic text"""

            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.1}
                },
                timeout=35
            )
            resp.raise_for_status()
            resp_json = resp.json()
            if "error" in resp_json:
                raise ValueError(resp_json["error"].get("message", "unknown"))
            raw = resp_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            clean = re.sub(r'^```(?:json)?\s*', '', raw.strip())
            clean = re.sub(r'\s*```$', '', clean.strip())
            m = re.search(r'\{.*\}', clean, re.DOTALL)
            if m:
                result = json.loads(m.group())
                if isinstance(result.get("key_points"), list):
                    result["ai_powered"] = True
                    result["word_count"] = wc
                    result.setdefault("summary", "")
                    return result
        except requests.exceptions.Timeout:
            logger.warning("Gemini timed out — using keyword fallback")
        except json.JSONDecodeError as e:
            logger.warning(f"Gemini JSON parse error: {e}")
        except Exception as e:
            logger.warning(f"Gemini API failed: {type(e).__name__}: {e}")

    # ── Smart keyword fallback ────────────────────────────────────
    keywords = {
        "decision":  ["decided", "agreed", "approved", "confirmed", "will use", "chosen", "selected", "finalized"],
        "action":    ["will", "need to", "should", "must", "assigned to", "going to", "i'll", "we'll", "you'll"],
        "deadline":  ["by friday", "deadline", "due", "end of week", "eod", "by next", "by tomorrow", "within"],
        "follow_up": ["follow up", "revisit", "next meeting", "schedule", "check in", "circle back", "look into"],
    }
    key_points, seen = [], set()
    lines = [l.strip() for l in transcript.replace(". ", "\n").split("\n") if len(l.strip()) > 20]
    for line in lines:
        if line in seen: continue
        seen.add(line)
        ll = line.lower()
        for ktype, words in keywords.items():
            if any(w in ll for w in words):
                key_points.append({"type": ktype, "text": line[:200], "timestamp": ""})
                break
        if len(key_points) >= 8: break

    if not key_points:
        key_points = [
            {"type": "action",    "text": "Review the transcript and identify action items manually.", "timestamp": ""},
            {"type": "follow_up", "text": "Add GEMINI_API_KEY to .env to enable AI-powered extraction.", "timestamp": ""},
        ]
        summary = f"Transcript ({wc} words) — no key points auto-detected. Enable Gemini AI for full analysis."
    else:
        summary = f"{len(key_points)} key points detected from {wc}-word transcript (keyword-based). Add GEMINI_API_KEY for full AI analysis."

    return {"key_points": key_points, "summary": summary, "word_count": wc, "ai_powered": False}


# ── Translation ───────────────────────────────────────────────────────────────

def gemini_translate(text: str, target_lang: str, source_lang: str,
                     lang_name: str, api_key: str) -> str | None:
    """Translate with Gemini, correcting speech-to-text errors silently."""
    if not api_key or not text:
        return None
    prompt = (
        f"You are an expert real-time speech translator.\n"
        f"Task: Translate from {source_lang.upper()} to {lang_name}.\n"
        f"Rules:\n"
        f"1. Fix speech-to-text transcription errors silently\n"
        f"2. Translate naturally into {lang_name}\n"
        f"3. Output ONLY the final {lang_name} translation\n"
        f"4. No explanations, no original text, no labels\n"
        f"Input: \"{text[:500]}\"\n"
        f"{lang_name} translation:"
    )
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 400, "temperature": 0.1}},
            timeout=8
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        result = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if result and result[0] in ('"', "'") and result[-1] in ('"', "'"):
            result = result[1:-1]
        return result or None
    except Exception as e:
        logger.warning(f"Gemini translate failed: {e}")
        return None
