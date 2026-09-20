# 🧪 Rick Voice Alexa Skill (Railway Backend)

Custom Alexa Skill backend running on FastAPI, using OpenAI for Rick Sanchez personality generation and [rick-voice](https://github.com/mattzzz/rick-voice) for character voice synthesis (via Fish Audio).

---

## 🚀 Environment Variables (Railway)

Set the following variables in your Railway project dashboard:

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `FISH_API_KEY` | Your Fish Audio API key (from [fish.audio](https://fish.audio)) |
| `PUBLIC_URL` | Your Railway public URL (e.g. `https://your-service.up.railway.app`) |

---

## 📡 Alexa Skill Setup

1. In the **Alexa Developer Console**, go to **Endpoint**.
2. Select **HTTPS**.
3. Default Region URL: `https://<YOUR-RAILWAY-APP>.up.railway.app/alexa`
4. SSL Certificate: Select `"My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority"`.
5. Under **Interaction Model**, create an Intent with a slot `Query` (`AMAZON.SearchQuery`) so queries are forwarded to Rick.

---

## 🛠️ Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export OPENAI_API_KEY="your-key"
export FISH_API_KEY="your-key"
export PUBLIC_URL="http://localhost:8000"

uvicorn main:app --reload --port 8000
```
