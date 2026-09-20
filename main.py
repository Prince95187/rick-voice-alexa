import os
import random
import uuid
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from rick_voice import RickVoice

app = FastAPI(title="Rick Alexa Skill Backend")

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

RICK_SYSTEM_PROMPT = (
    "You are Rick Sanchez from Rick and Morty. "
    "Be cynical, grumpy, stutter occasionally (e.g. 'I-I-I', 'M-Morty'), "
    "belittle the user slightly, but answer their question. "
    "Keep it short and punchy (1 to 2 sentences max)."
)

FALLBACK_QUOTES = [
    "I turned myself into a pickle, Morty! I'm Pickle Rick!",
    "Nobody exists on purpose. Nobody belongs anywhere. Everybody's gonna die. Come watch TV.",
    "Wubba lubba dub dub! What do you want from me?",
    "Listen to me, Morty. The universe is a cruel, uncaring void. Now what was your question?",
    "To live is to risk it all. Otherwise you're just an inert chunk of randomly assembled molecules.",
]

def get_base_url():
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
    return os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")

def generate_rick_text(user_query: str) -> str:
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    # 1. Prefer Gemini (Free forever)
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"Instruction: {RICK_SYSTEM_PROMPT}\nUser input: {user_query}"}
                        ],
                    }
                ]
            }
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Clean enclosing quotes if model added them
                if text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]
                return text
        except Exception:
            pass

    # 2. Fallback to OpenAI if configured
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": RICK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_query},
                ],
                max_tokens=120,
            )
            return completion.choices[0].message.content or "Wubba lubba dub dub!"
        except Exception:
            pass

    # 3. Static fallback quotes
    return random.choice(FALLBACK_QUOTES)

@app.get("/")
async def health():
    active_llm = "gemini-2.5-flash (Google Free Tier)" if os.getenv("GEMINI_API_KEY") else ("openai" if os.getenv("OPENAI_API_KEY") else "static-quotes")
    return {
        "status": "online",
        "service": "rick-voice-alexa",
        "active_llm": active_llm,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "fish_audio_configured": bool(os.getenv("FISH_API_KEY")),
        "base_url": get_base_url(),
    }

@app.get("/test-llm")
async def test_llm(query: str = "Who are you and what do you do?"):
    """Test the Rick personality text generation directly."""
    reply = generate_rick_text(query)
    return {
        "user_query": query,
        "rick_reply": reply,
        "llm_provider": "gemini" if os.getenv("GEMINI_API_KEY") else ("openai" if os.getenv("OPENAI_API_KEY") else "static")
    }

@app.get("/test-voice")
async def test_voice(text: str = "I turned myself into a pickle, Morty!"):
    """Test Rick voice synthesis directly in your browser!"""
    try:
        rick = RickVoice()
        audio_bytes = rick.synthesize(text)
        file_id = str(uuid.uuid4())
        filepath = os.path.join(CACHE_DIR, f"{file_id}.mp3")
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        return FileResponse(filepath, media_type="audio/mpeg", filename="rick.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice synthesis error: {str(e)}")

@app.post("/alexa")
async def alexa_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req = data.get("request", {})
    req_type = req.get("type", "")

    if req_type == "LaunchRequest":
        user_text = "Say hello to me."
    elif req_type == "IntentRequest":
        intent = req.get("intent", {})
        intent_name = intent.get("name", "")

        if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return build_alexa_speech_response("Fine, whatever. I was busy in the garage anyway.")

        slots = intent.get("slots", {})
        query_slot = slots.get("Query") or slots.get("query") or {}
        user_text = query_slot.get("value") or "Say something sarcastic to me."
    elif req_type == "SessionEndedRequest":
        return build_alexa_speech_response("Later.", end_session=True)
    else:
        user_text = "Say something cynical."

    # 1. Generate text using Google Gemini
    rick_text = generate_rick_text(user_text)

    # 2. Synthesize with rick-voice
    try:
        rick = RickVoice()
        audio_bytes = rick.synthesize(rick_text)
        file_id = str(uuid.uuid4())
        filepath = os.path.join(CACHE_DIR, f"{file_id}.mp3")
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        base_url = get_base_url()
        audio_url = f"{base_url}/audio/{file_id}.mp3"
        return {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "SSML",
                    "ssml": f"<speak><audio src='{audio_url}'/></speak>",
                },
                "shouldEndSession": True,
            },
        }
    except Exception as e:
        # If TTS fails, speak the text directly with Alexa's voice
        return build_alexa_speech_response(f"{rick_text} (Note: Voice synth unavailable: {str(e)})")

@app.get("/audio/{file_id}.mp3")
async def serve_audio(file_id: str):
    filepath = os.path.join(CACHE_DIR, f"{file_id}.mp3")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(filepath, media_type="audio/mpeg")

def build_alexa_speech_response(text: str, end_session: bool = True):
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": text,
            },
            "shouldEndSession": end_session,
        },
    }
