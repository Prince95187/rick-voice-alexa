import os
import random
import uuid
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
import rvc_engine

app = FastAPI(title="Rick Sanchez Alexa Skill (Local RVC + Gemini)")

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

def get_base_url(request: Request = None):
    if request:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        proto = request.headers.get("x-forwarded-proto", "https")
        if host:
            return f"{proto}://{host}"
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
    return os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")

@app.on_event("startup")
async def startup_event():
    # Pre-warm RVC models into memory
    rvc_engine.init_models()

def generate_rick_text(user_query: str) -> str:
    gemini_key = os.getenv("GEMINI_API_KEY")

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
                if text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]
                return text
        except Exception:
            pass

    return random.choice(FALLBACK_QUOTES)

@app.get("/")
async def health(request: Request):
    return {
        "status": "online",
        "service": "rick-voice-alexa-rvc",
        "voice_engine": "Self-Hosted RVC (100% Free Forever)",
        "model_loaded": rvc_engine._INITIALIZED,
        "llm_engine": "Google Gemini 2.5 Flash",
        "base_url": get_base_url(request),
    }

@app.get("/test-voice")
async def test_voice(text: str = "I turned myself into a pickle, Morty! I'm Pickle Rick!"):
    """Test Rick voice synthesis directly in your browser with RVC!"""
    try:
        file_id = str(uuid.uuid4())
        filepath = os.path.join(CACHE_DIR, f"{file_id}.mp3")
        actual_path = await rvc_engine.synthesize_rick(text, filepath)
        media_type = "audio/mpeg" if actual_path.endswith(".mp3") else "audio/wav"
        return FileResponse(actual_path, media_type=media_type, filename=os.path.basename(actual_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RVC voice synthesis error: {str(e)}")

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

    # 1. Generate personality reply with Google Gemini
    rick_text = generate_rick_text(user_text)

    # 2. Synthesize Rick voice using RVC
    try:
        file_id = str(uuid.uuid4())
        target_path = os.path.join(CACHE_DIR, f"{file_id}.mp3")
        actual_file = await rvc_engine.synthesize_rick(rick_text, target_path)

        base_url = get_base_url(request)
        ext = os.path.splitext(actual_file)[1].lstrip(".")
        audio_url = f"{base_url}/audio/{file_id}.{ext}"

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
        return build_alexa_speech_response(f"{rick_text} (Voice error: {str(e)})")

@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    filepath = os.path.join(CACHE_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Audio file not found")
    media = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
    return FileResponse(filepath, media_type=media)

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

if __name__ == "__main__":
    import uvicorn
    raw_port = os.getenv("PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError:
        port = 8000
    print(f"Starting server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
