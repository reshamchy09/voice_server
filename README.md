# Resham Voice API

Self-hosted Nepali + Hindi text-to-speech web app. Frontend: HTML/CSS/JavaScript. Backend: Python FastAPI. Speech engine: Piper TTS. Voice files are downloaded on first use into `models/`.

## Requirements
- Ubuntu 22.04/24.04 (or another Python 3.10+ environment)
- Internet for the first model download
- Recommended: 2 GB+ RAM and several hundred MB of free disk space

## Run (Windows)
1. Install Python 3.10+ from python.org (tick **Add python.exe to PATH**).
2. Unzip, then double-click `run.bat` (or run it in Command Prompt/PowerShell).
3. Open `http://localhost:8000`.

Manual: `py -3 -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `python -m uvicorn main:app --port 8000`. Pre-download voices: `python -m piper.download_voices hi_IN-pratham-medium --download-dir models`.

## Run (Linux/macOS)
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
unzip Resham_Voice_API.zip
cd resham_voice_api
chmod +x run.sh
./run.sh
```
Open `http://YOUR_SERVER_IP:8000` for the web UI and `http://YOUR_SERVER_IP:8000/docs` for interactive API docs. Keep port 8000 private behind a reverse proxy/firewall for production.

## Supported voices
- `ne`: `ne_NP-google-x_low` (Nepali; low quality/compact voice)
- `hi`: `hi_IN-pratham-medium` (Hindi; medium voice)
- `en`: `en_US-lessac-medium` (English; medium voice)

Models download automatically when first used. You can also pre-download them:
```bash
source .venv/bin/activate
python -m piper.download_voices ne_NP-google-x_low --download-dir models
python -m piper.download_voices hi_IN-pratham-medium --download-dir models
```
Check model cards and licenses before commercial use. Nepali Piper voice is an x_low model, so quality may be less natural than larger research checkpoints. Available alternatives include Nepali VITS/Matcha/OmniVoice models, but they require a different inference pipeline and are not plug-compatible with Piper.

## REST API
`POST /v1/audio/speech` with JSON:
```json
{"text":"नमस्कार, तपाईंलाई कस्तो छ?","language":"ne","length_scale":1.0}
```
Set `language` to `ne`, `hi` or `en`; response is `audio/wav`. `length_scale` controls speed (0.5–2.0; 1.0 is normal).

Other endpoints:
- `GET /health`
- `GET /v1/voices`
- `POST /v1/models/ne/download`
- `POST /v1/models/hi/download`
- `POST /v1/models/en/download`

All endpoints except `/health` need an API key when called from another app (the bundled web page needs none).

## Connect from another app
Use the server base URL and POST to `/v1/audio/speech`. Example JavaScript:
```js
const response = await fetch('https://voice.example.com/v1/audio/speech', {
  method: 'POST', headers: {'Content-Type':'application/json', 'X-API-Key':'rv_yourappkey'},
  body: JSON.stringify({text:'नमस्ते', language:'ne'}) // 'ne' | 'hi' | 'en'
});
const audioBlob = await response.blob();
const audioUrl = URL.createObjectURL(audioBlob);
```

## Production notes
- Run behind Nginx/Caddy and HTTPS; do not expose the development server directly.
- Restrict CORS with `CORS_ORIGINS=https://your-app.example.com`.
- API-key authentication is built in for other apps. Add rate limiting (e.g. at Nginx) because the bundled web page works without a key.
- The first model download needs internet; later synthesis runs locally.

## API keys
On first start an **admin key** is generated, saved to `api_keys.json` and printed in the console. Paste it into the **API KEY** box on the web page (remembered in your browser).

**Generate keys for other apps:** on the web page use *API keys for other apps* (name the app → Generate key; copy it, it is shown once; Revoke to delete). Or via API with the admin key:
```
curl -X POST http://localhost:8000/v1/keys -H "X-API-Key: ADMIN_KEY" -H "Content-Type: application/json" -d "{\"name\":\"Android app\"}"
curl http://localhost:8000/v1/keys -H "X-API-Key: ADMIN_KEY"
curl -X DELETE http://localhost:8000/v1/keys/KEY_ID -H "X-API-Key: ADMIN_KEY"
```
Other apps use their key to make speech:
```
curl -X POST http://localhost:8000/v1/audio/speech -H "X-API-Key: rv_appkey" -H "Content-Type: application/json" -o out.wav -d "{\"text\":\"नमस्ते\",\"language\":\"hi\"}"
```
Kotlin (OkHttp) example, `language` = `ne`, `hi` or `en`:
```kotlin
val body = """{"text":"Hello world","language":"en","length_scale":1.0}"""
    .toRequestBody("application/json".toMediaType())
val request = Request.Builder()
    .url("https://YOUR_SERVER/v1/audio/speech")
    .addHeader("X-API-Key", "rv_appkey")
    .post(body).build()
OkHttpClient().newCall(request).execute().use { it.body!!.bytes() } // WAV bytes
```
`Authorization: Bearer rv_appkey` also works. Only admin keys can manage keys. Disable auth with `REQUIRE_API_KEY=0`. `/health` stays public.