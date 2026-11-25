from pathlib import Path
import json, os, secrets, subprocess, sys, threading, uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

BASE = Path(__file__).resolve().parent
MODELS = BASE / "models"
OUTPUT = BASE / "generated"
MODELS.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

# Piper voice identifiers. These are downloaded from the Piper voice catalogue,
# which is hosted on Hugging Face. Check each model card/license before commercial use.
VOICES = {
    "ne": {"name": "Nepali Google (medium)", "id": "ne_NP-google-medium"},
    "hi": {"name": "Hindi Pratham (medium)", "id": "hi_IN-pratham-medium"},
    "en": {"name": "English Lessac (medium)", "id": "en_US-lessac-medium"},
}

app = FastAPI(title="Resham Voice API", version="1.0.0", description="Self-hosted Nepali and Hindi text-to-speech API")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])


# ---------------- API key authentication ----------------
# Keys live in api_keys.json. On first start an ADMIN key is generated, saved and printed.
# The admin key can create/list/revoke keys for other apps (POST/GET/DELETE /v1/keys, or the web page).
# Legacy api_keys.txt / env RESHAM_API_KEYS (comma-separated) are imported as normal keys.
# Set REQUIRE_API_KEY=0 to disable authentication.
KEY_FILE = BASE / "api_keys.json"
LEGACY_FILE = BASE / "api_keys.txt"
REQUIRE_KEY = os.getenv("REQUIRE_API_KEY", "1").lower() not in ("0", "false", "no")
_lock = threading.Lock()


def _new_key() -> str:
    return "rv_" + secrets.token_urlsafe(24)


def _record(name: str, admin: bool = False, key: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name, "key": key or _new_key(), "admin": admin,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _save():
    KEY_FILE.write_text(json.dumps(KEYS, indent=2), encoding="utf-8")


def load_keys() -> list:
    keys = []
    if KEY_FILE.exists():
        keys = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    else:
        legacy = [l.strip() for l in LEGACY_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if LEGACY_FILE.exists() else []
        legacy += [k.strip() for k in os.getenv("RESHAM_API_KEYS", "").split(",") if k.strip()]
        keys = [_record("Imported key", admin=(i == 0), key=k) for i, k in enumerate(legacy)]
    if REQUIRE_KEY and not any(k.get("admin") for k in keys):
        keys.insert(0, _record("Admin", admin=True))
        print(f"\n  Admin API key: {keys[0]['key']}\n  Saved in {KEY_FILE}\n")
    return keys


KEYS = load_keys()
if REQUIRE_KEY:
    _save()
_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def _same_site(request: Request) -> bool:
    """True when the call comes from this server's own web page (no key needed there)."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    return bool(host) and urlparse(origin).netloc == host


def require_key(request: Request, x_api_key: str = Security(_header), bearer: HTTPAuthorizationCredentials = Security(_bearer)):
    if not REQUIRE_KEY:
        return {"admin": False, "id": None}
    supplied = (x_api_key or (bearer.credentials if bearer else "")).encode()
    if supplied:
        for rec in list(KEYS):
            if secrets.compare_digest(supplied, rec["key"].encode()):
                return rec
    # Main web page (same origin) works without a key; other apps still need one.
    if not supplied and _same_site(request):
        return {"admin": False, "id": None, "web": True}
    raise HTTPException(401, "Invalid or missing API key. Send header 'X-API-Key: <key>' or 'Authorization: Bearer <key>'.",
                        headers={"WWW-Authenticate": "Bearer"})


def require_admin(rec: dict = Depends(require_key)):
    if not REQUIRE_KEY:
        raise HTTPException(400, "Authentication is disabled (REQUIRE_API_KEY=0); key management is unavailable.")
    if not rec.get("admin"):
        raise HTTPException(403, "Admin API key required to manage keys.")
    return rec


class KeyRequest(BaseModel):
    name: str = Field(default="Other app", min_length=1, max_length=60)


def _public(rec: dict, reveal: bool = False) -> dict:
    out = {k: rec[k] for k in ("id", "name", "admin", "created")}
    out["key"] = rec["key"] if reveal else rec["key"][:7] + "…" + rec["key"][-4:]
    return out

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    language: str = Field(default="ne", pattern="^(ne|hi|en)$")
    length_scale: float = Field(default=1.0, ge=0.5, le=2.0)


# Windows: hide console popups for child processes and force UTF-8 so Devanagari text survives.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def ensure_voice(language: str) -> Path:
    voice_id = VOICES[language]["id"]
    model = MODELS / f"{voice_id}.onnx"
    config = MODELS / f"{voice_id}.onnx.json"
    if model.exists() and config.exists():
        return model
    # Piper's downloader resolves the correct Hugging Face model and config files.
    cmd = [sys.executable, "-m", "piper.download_voices", voice_id, "--download-dir", str(MODELS)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, **NO_WINDOW)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(503, f"Could not download voice model {voice_id}: {exc.stderr[-800:]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Voice model download timed out. Retry after checking internet connection.")
    if not model.exists() or not config.exists():
        raise HTTPException(503, f"Voice model files were not found after download: {voice_id}")
    return model


def synthesize(text: str, language: str, length_scale: float, destination: Path):
    model = ensure_voice(language)
    # Run Piper as a module of the current interpreter: works on Windows/Linux/macOS
    # without needing the venv's Scripts/bin folder on PATH.
    cmd = [sys.executable, "-m", "piper", "--model", str(model), "--output_file", str(destination), "--length_scale", str(length_scale)]
    try:
        # Text is sent as UTF-8 bytes (Windows default codepage would corrupt Nepali/Hindi).
        subprocess.run(cmd, input=text.encode("utf-8"), check=True, capture_output=True, timeout=180, env=CHILD_ENV, **NO_WINDOW)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500, f"Piper speech generation failed: {exc.stderr.decode('utf-8', 'replace')[-800:]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Speech generation timed out.")
    if not destination.exists() or destination.stat().st_size == 0:
        raise HTTPException(500, "Piper did not create an audio file.")

@app.get("/health")
def health():
    return {"status": "ok", "service": "Resham Voice API", "languages": list(VOICES), "auth_required": REQUIRE_KEY}

@app.post("/v1/keys", dependencies=[Depends(require_admin)])
def create_key(payload: KeyRequest):
    """Generate a new API key for another app. The full key is shown only in this response."""
    with _lock:
        rec = _record(payload.name.strip() or "Other app")
        KEYS.append(rec)
        _save()
    return _public(rec, reveal=True)

@app.get("/v1/keys", dependencies=[Depends(require_admin)])
def list_keys():
    return [_public(k) for k in KEYS]

@app.delete("/v1/keys/{key_id}", dependencies=[Depends(require_admin)])
def revoke_key(key_id: str):
    with _lock:
        rec = next((k for k in KEYS if k["id"] == key_id), None)
        if not rec:
            raise HTTPException(404, "Key not found")
        if rec.get("admin") and sum(1 for k in KEYS if k.get("admin")) == 1:
            raise HTTPException(400, "Cannot revoke the only admin key")
        KEYS.remove(rec)
        _save()
    return {"status": "revoked", "id": key_id}

@app.get("/v1/voices", dependencies=[Depends(require_key)])
def voices():
    return {code: {**data, "downloaded": (MODELS / f"{data['id']}.onnx").exists()} for code, data in VOICES.items()}

@app.post("/v1/models/{language}/download", dependencies=[Depends(require_key)])
def download_model(language: str):
    if language not in VOICES:
        raise HTTPException(404, "Supported languages: ne, hi, en")
    model = ensure_voice(language)
    return {"status": "downloaded", "language": language, "model": model.name}

@app.post("/v1/audio/speech", dependencies=[Depends(require_key)])
def create_speech(payload: SpeechRequest):
    if not payload.text.strip():
        raise HTTPException(422, "Text cannot be blank")
    filename = f"{uuid.uuid4().hex}.wav"
    path = OUTPUT / filename
    synthesize(payload.text.strip(), payload.language, payload.length_scale, path)
    # Delete the temp WAV after it has been sent (also avoids disk build-up).
    return FileResponse(path, media_type="audio/wav", filename=f"resham-{payload.language}.wav",
                        background=BackgroundTask(lambda: path.unlink(missing_ok=True)))

app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        sys.exit("Missing packages. Run:  py -m pip install -r requirements.txt")
    print("Open http://localhost:8096 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=8096)