import os
import random
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from openai import OpenAI
from rick_voice import RickVoice

app = FastAPI(title="Rick Alexa Skill Backend")

# Audio cache directory
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Auto-detect public URL from Railway variables or fallback
def get_base_url():
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
    return os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

def get_rick_voice():
    # Will use FISH_API_KEY from environment
    return RickVoice()

FALLBACK_QUOTES = [
    "I turned myself into a pickle, Morty! I'm Pickle Rick!",
    "Nobody exists on purpose. Nobody belongs anywhere. Everybody's gonna die. Come watch TV.",
    "Wubba lubba dub dub! What do you want from me?",
    "Listen to me, Morty. The universe is a cruel, uncaring void. Now what was your question?",
    "To live is to risk it all. Otherwise you're just an inert chunk of randomly assembled molecules.",
]

@app.get("/")
async def health():
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_fish = bool(os.getenv("FISH_API_KEY"))
    return {
        "status": "online",
        "service": "rick-voice-alexa",
        "openai_configured": has_openai,
        "fish_audio_configured": has_fish,
        "base_url": get_base_url(),
        "hint": "Set OPENAI_API_KEY in Railway to enable dynamic GPT-4o replies. Otherwise fallback Rick quotes are used."
    }

@app.get("/test-voice")
async def test_voice(text: str = "I turned myself into a pickle, Morty!"):
    """Test Rick voice synthesis directly in your browser!"""
    try:
        rick = get_rick_voice()
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

    # 1. Generate text with OpenAI if configured, otherwise pick a classic Rick quote
    client = get_openai_client()
    if client:
        try:
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Rick Sanchez from Rick and Morty. "
                            "Be cynical, grumpy, stutter occasionally (e.g. 'I-I-I', 'M-Morty'), "
                            "belittle the user slightly, but answer their question. "
                            "Keep it short and punchy (1 to 2 sentences max)."
                        ),
                    },
                    {"role": "user", "content": user_text},
                ],
                max_tokens=120,
            )
            rick_text = completion.choices[0].message.content or "Wubba lubba dub dub!"
        except Exception:
            rick_text = random.choice(FALLBACK_QUOTES)
    else:
        rick_text = random.choice(FALLBACK_QUOTES)

    # 2. Synthesize with rick-voice
    try:
        rick = get_rick_voice()
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
        return build_alexa_speech_response(f"Voice synth failed, Morty. Error: {str(e)}")

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
