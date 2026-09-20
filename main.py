import os
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from openai import OpenAI
from rick_voice import RickVoice

app = FastAPI(title="Rick Alexa Skill Backend")

# Initialize clients
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# RickVoice uses FISH_API_KEY from environment by default
rick = RickVoice()

# Audio cache folder to serve files back to Alexa
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Base public domain from Railway (e.g. https://xyz.up.railway.app)
BASE_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")


@app.get("/")
async def health():
    return {"status": "ok", "service": "rick-voice-alexa"}


@app.post("/alexa")
async def alexa_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req = data.get("request", {})
    req_type = req.get("type", "")

    # Handle LaunchRequest or IntentRequest
    if req_type == "LaunchRequest":
        user_text = "Say hello to me."
    elif req_type == "IntentRequest":
        intent = req.get("intent", {})
        intent_name = intent.get("name", "")

        # Handle built-in stop / cancel
        if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return build_alexa_speech_response("Fine, whatever. I was busy in the garage anyway.")

        # Extract slot value (e.g. "Query" or fallback to generic question)
        slots = intent.get("slots", {})
        query_slot = slots.get("Query") or slots.get("query") or {}
        user_text = query_slot.get("value") or "Say something sarcastic to me."
    elif req_type == "SessionEndedRequest":
        return build_alexa_speech_response("Later.", end_session=True)
    else:
        user_text = "Say something cynical."

    # 1. Ask OpenAI with Rick personality
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
    except Exception as e:
        rick_text = f"My portal gun is broken, and OpenAI failed: {str(e)}"

    # 2. Synthesize Rick's voice using rick-voice (Fish Audio)
    try:
        audio_bytes = rick.synthesize(rick_text)
        file_id = str(uuid.uuid4())
        filepath = os.path.join(CACHE_DIR, f"{file_id}.mp3")
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        audio_url = f"{BASE_URL}/audio/{file_id}.mp3"
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
        # Fallback to plain SSML speech if TTS voice fails
        return build_alexa_speech_response(f"Voice synth broke, Morty. Here is what I was gonna say: {rick_text}")


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
