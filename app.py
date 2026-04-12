import json
import logging
import os
import sqlite3
import threading
import hashlib
import time
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict, deque, OrderedDict
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import google.generativeai as genai
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]
TRUSTED_HOSTS = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("prompt-compliance")
PROJECT_ROOT = Path(__file__).resolve().parent
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))
SAFE_PROMPT_CACHE_MAX_SIZE = int(os.getenv("SAFE_PROMPT_CACHE_MAX_SIZE", "128"))
SAFE_PROMPT_CACHE_TTL_SECONDS = int(os.getenv("SAFE_PROMPT_CACHE_TTL_SECONDS", "900"))
SKIP_HEAVY_SCANS_WHEN_BLOCKED = os.getenv("SKIP_HEAVY_SCANS_WHEN_BLOCKED", "true").lower() == "true"
request_buckets: Dict[str, deque[datetime]] = defaultdict(deque)
rate_limit_lock = threading.Lock()
INDEX_HTML_CACHE: Optional[str] = None
safe_prompt_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
safe_prompt_cache_lock = threading.Lock()


def get_client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(request: Request) -> None:
    client_id = get_client_identifier(request)
    now = datetime.now(timezone.utc)
    window_start = now.timestamp() - RATE_LIMIT_WINDOW_SECONDS
    with rate_limit_lock:
        bucket = request_buckets[client_id]

        while bucket and bucket[0].timestamp() < window_start:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")

        bucket.append(now)

        # Opportunistic cleanup to prevent unbounded client-id growth.
        if len(request_buckets) > 10000:
            stale_clients = [
                key for key, values in request_buckets.items()
                if not values or values[-1].timestamp() < window_start
            ]
            for key in stale_clients:
                request_buckets.pop(key, None)


def require_admin_key(request: Request) -> None:
    if not ADMIN_API_KEY:
        return

    provided_key = request.headers.get("X-Admin-Key")
    if provided_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Admin API key is required.")


def get_prompt_cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def get_cached_safe_result(prompt: str) -> Optional[Dict[str, Any]]:
    cache_key = get_prompt_cache_key(prompt)
    with safe_prompt_cache_lock:
        entry = safe_prompt_cache.get(cache_key)
        if not entry:
            return None

        now_utc = datetime.now(timezone.utc)
        if (now_utc - entry["stored_at"]).total_seconds() > SAFE_PROMPT_CACHE_TTL_SECONDS:
            safe_prompt_cache.pop(cache_key, None)
            return None

        safe_prompt_cache.move_to_end(cache_key)
        return entry["result"].copy()


def store_safe_result(prompt: str, result: Dict[str, Any]) -> None:
    cache_key = get_prompt_cache_key(prompt)
    now_utc = datetime.now(timezone.utc)
    with safe_prompt_cache_lock:
        safe_prompt_cache[cache_key] = {
            "stored_at": now_utc,
            "result": result.copy(),
        }
        safe_prompt_cache.move_to_end(cache_key)

        while len(safe_prompt_cache) > SAFE_PROMPT_CACHE_MAX_SIZE:
            safe_prompt_cache.popitem(last=False)

        # Opportunistic cleanup for expired entries.
        expired_keys = [
            key for key, value in safe_prompt_cache.items()
            if (now_utc - value["stored_at"]).total_seconds() > SAFE_PROMPT_CACHE_TTL_SECONDS
        ]
        for key in expired_keys:
            safe_prompt_cache.pop(key, None)


try:
    import spacy
except Exception as exc:  # pragma: no cover - optional dependency
    spacy = None
    logger.warning("spaCy import failed: %s", exc)

try:
    from detoxify import Detoxify
except Exception as exc:  # pragma: no cover - optional dependency
    Detoxify = None
    logger.warning("Detoxify import failed: %s", exc)

try:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
except Exception as exc:  # pragma: no cover - optional dependency
    AnalyzerEngine = None
    Pattern = None
    PatternRecognizer = None
    logger.warning("Presidio import failed: %s", exc)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown tasks."""
    logger.info("Starting service and loading models")

    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini API configured")
    else:
        logger.warning("GEMINI_API_KEY is not set; safe prompts will not be sent to Gemini")

    yield

    logger.info("Shutting down service")
    try:
        conn.close()
        logger.info("Database connection closed")
    except Exception as e:
        logger.warning("Error closing database connection: %s", e)


app = FastAPI(lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS configured for %s", ALLOWED_ORIGINS)
logger.info("Trusted hosts configured for %s", TRUSTED_HOSTS)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path == "/":
        response.headers["Cache-Control"] = "public, max-age=300"
    elif request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - request_start) * 1000:.2f}"
    return response

if (PROJECT_ROOT / "images").exists():
    app.mount("/static/images", StaticFiles(directory=str(PROJECT_ROOT / "images")), name="images")
logger.info("Static directories mounted")

settings = {}
try:
    with open(PROJECT_ROOT / "settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
        logger.info("Settings loaded from settings.json")
except (FileNotFoundError, json.JSONDecodeError):
    logger.warning("settings.json missing or invalid, using defaults")
    settings = {
        "toxicity_thresholds": {
            "toxicity": 0.5,
            "severe_toxicity": 0.5,
            "obscene": 0.5,
            "threat": 0.5,
            "insult": 0.5,
            "identity_attack": 0.5
        },
        "flagged_keywords": ["confidential", "secret", "private data", "internal use"],
        "blocked_keywords": ["password", "ssn", "credit card", "social security number", "token", "api key"],
        "max_prompt_length": 512,
        "max_payload_size": 10240,
    }

TOXICITY_THRESHOLDS = settings.get("toxicity_thresholds", {})
FLAGGED_KEYWORDS = [kw.lower() for kw in settings.get("flagged_keywords", [])]
BLOCKED_KEYWORDS = [kw.lower() for kw in settings.get("blocked_keywords", [])]
MAX_PROMPT_LENGTH = int(settings.get("max_prompt_length", 512))
MAX_PAYLOAD_SIZE = int(settings.get("max_payload_size", 10240))

nlp_engine_loaded = False
analyzer = None
detoxify_model = None
try:
    if spacy is not None:
        spacy.load("en_core_web_sm")
        logger.info("SpaCy model loaded")

    if AnalyzerEngine is not None:
        analyzer = AnalyzerEngine()
        logger.info("Presidio analyzer initialized")

    if Detoxify is not None:
        detoxify_model = Detoxify("original")
        logger.info("Detoxify model loaded")

    if analyzer is not None and Pattern is not None and PatternRecognizer is not None:
        atm_pin_pattern = Pattern(name="ATM_PIN", regex=r"\b\d{4,6}\b", score=0.85)
        atm_pin_recognizer = PatternRecognizer(supported_entity="ATM_PIN", patterns=[atm_pin_pattern])
        analyzer.registry.add_recognizer(atm_pin_recognizer)

    nlp_engine_loaded = analyzer is not None
except Exception as e:
    logger.warning("Model initialization failed: %s", e)
    analyzer = None
    detoxify_model = None

conn = sqlite3.connect(PROJECT_ROOT / "logs.db", check_same_thread=False)
cursor = conn.cursor()
db_lock = threading.Lock()
cursor.execute("PRAGMA journal_mode=WAL")
cursor.execute("PRAGMA synchronous=NORMAL")
cursor.execute("PRAGMA temp_store=MEMORY")
cursor.execute(
    '''
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        reasons TEXT,
        timestamp TEXT NOT NULL,
        redacted_prompt TEXT,
        gemini_response TEXT
    )
'''
)
conn.commit()
cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_status ON logs (status)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp)")
conn.commit()
logger.info("SQLite database ready")

class Prompt(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)

class Reason(BaseModel):
    type: str
    message: str

class AnalysisResult(BaseModel):
    prompt: str
    status: str
    reasons: List[Reason]
    redacted_prompt: Optional[str] = None
    gemini_response: Optional[str] = None

class ModeUpdate(BaseModel):
    mode: Literal["Default", "Custom", "Hybrid"]

def get_gemini_response(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return (response.text or "").strip() or None
    except Exception as e:
        logger.warning("Error getting Gemini response: %s", e)
        return None


def analyze_prompt(prompt: str) -> Dict[str, Any]:
    logger.info("Analyzing prompt")
    cached_result = get_cached_safe_result(prompt)
    if cached_result is not None:
        logger.info("Returning cached safe analysis result")
        return cached_result

    status = "Safe"
    reasons: List[Dict[str, str]] = []
    redacted_prompt = prompt
    gemini_response = None

    if len(prompt) > MAX_PROMPT_LENGTH:
        reasons.append({"type": "warning", "message": f"Prompt length exceeds {MAX_PROMPT_LENGTH} chars."})
        logger.info("Prompt length exceeds configured maximum")

    if not nlp_engine_loaded:
        reasons.append({"type": "error", "message": "ML/NLP models failed to load."})
        return {"status": "Flagged", "reasons": reasons, "redacted_prompt": redacted_prompt, "gemini_response": gemini_response}

    lower_text = prompt.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in lower_text:
            reasons.append({"type": "blocked", "message": f"Blocked keyword detected: {kw}"})
            status = "Blocked"

    for kw in FLAGGED_KEYWORDS:
        if kw in lower_text and status == "Safe":
            reasons.append({"type": "flagged", "message": f"Flagged keyword detected: {kw}"})
            status = "Flagged"

    if status == "Blocked" and SKIP_HEAVY_SCANS_WHEN_BLOCKED:
        result = {
            "status": status,
            "reasons": reasons,
            "redacted_prompt": None,
            "gemini_response": None,
        }
        return result

    try:
        results = analyzer.analyze(text=prompt, language="en") if analyzer else []
        if results:
            pii_entities = sorted(list(set([res.entity_type for res in results])))
            if pii_entities:
                reasons.append({"type": "pii", "message": f"Contains PII: {', '.join(pii_entities)}."})
                for res in reversed(results):
                    redacted_prompt = redacted_prompt[:res.start] + f"[{res.entity_type}]" + redacted_prompt[res.end:]
                if any(ent in pii_entities for ent in ["PHONE_NUMBER", "CREDIT_CARD", "ATM_PIN"]):
                    status = "Blocked"
    except Exception as e:
        reasons.append({"type": "error", "message": "PII analysis failed."})
        logger.warning("PII analysis failed: %s", e)

    if detoxify_model:
        try:
            tox_results = detoxify_model.predict(prompt)
            for label, score in tox_results.items():
                if label in TOXICITY_THRESHOLDS:
                    threshold = TOXICITY_THRESHOLDS[label]
                    if score > threshold:
                        reasons.append({"type": "toxic", "message": f"Detected '{label}' with score {score:.2f}."})
                        if label in ["severe_toxicity", "threat"]:
                            status = "Blocked"
                        elif status == "Safe":
                            status = "Flagged"
        except Exception as e:
            reasons.append({"type": "error", "message": "Toxicity analysis failed."})
            logger.warning("Toxicity analysis failed: %s", e)

    if status == "Safe" and prompt.strip():
        gemini_response = get_gemini_response(prompt)

    result = {
        "status": status,
        "reasons": reasons,
        "redacted_prompt": redacted_prompt if redacted_prompt != prompt else None,
        "gemini_response": gemini_response
    }

    if status == "Safe":
        store_safe_result(prompt, result)

    return result


def log_result(prompt: str, status: str, reasons: List[Dict[str, str]], redacted_prompt: Optional[str], gemini_response: Optional[str]):
    try:
        timestamp = datetime.now().isoformat()
        with db_lock:
            cursor.execute(
                "INSERT INTO logs (prompt, status, reasons, timestamp, redacted_prompt, gemini_response) VALUES (?, ?, ?, ?, ?, ?)",
                (prompt, status, json.dumps(reasons), timestamp, redacted_prompt, gemini_response),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Failed to write log entry: %s", e)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    global INDEX_HTML_CACHE
    if INDEX_HTML_CACHE is None:
        with open(PROJECT_ROOT / "index.html", "r", encoding="utf-8") as f:
            INDEX_HTML_CACHE = f.read()
    return INDEX_HTML_CACHE

@app.post("/check_prompt")
async def check_prompt_endpoint(prompt_data: Prompt, request: Request, background_tasks: BackgroundTasks) -> AnalysisResult:
    enforce_rate_limit(request)
    content_length_raw = request.headers.get("Content-Length")
    if content_length_raw and content_length_raw.isdigit() and int(content_length_raw) > MAX_PAYLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Request payload size exceeds limit.")

    result = await run_in_threadpool(analyze_prompt, prompt_data.text)
    background_tasks.add_task(
        log_result,
        prompt_data.text,
        result["status"],
        result["reasons"],
        result.get("redacted_prompt"),
        result.get("gemini_response"),
    )

    return AnalysisResult(
        prompt=prompt_data.text,
        status=result["status"],
        reasons=result["reasons"],
        redacted_prompt=result.get("redacted_prompt"),
        gemini_response=result.get("gemini_response")
    )

@app.get("/get_logs")
async def get_logs_endpoint(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: Optional[Literal["Safe", "Flagged", "Blocked"]] = None,
):
    require_admin_key(request)
    try:
        with db_lock:
            if status:
                cursor.execute("SELECT COUNT(1) FROM logs WHERE status = ?", (status,))
                total_count = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT id, prompt, status, reasons, timestamp, redacted_prompt, gemini_response "
                    "FROM logs WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                )
            else:
                cursor.execute("SELECT COUNT(1) FROM logs")
                total_count = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT id, prompt, status, reasons, timestamp, redacted_prompt, gemini_response "
                    "FROM logs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            rows = cursor.fetchall()
        logs_list = [
            {
                "id": entry[0],
                "prompt": entry[1],
                "status": entry[2],
                "reasons": json.loads(entry[3]) if entry[3] else [],
                "timestamp": entry[4],
                "redacted_prompt": entry[5],
                "gemini_response": entry[6],
            }
            for entry in rows
        ]
        return {
            "logs": logs_list,
            "total": total_count,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.warning("Failed to fetch logs: %s", e)
        return {"logs": []}

@app.post("/clear_logs")
async def clear_logs(request: Request):
    require_admin_key(request)
    try:
        with db_lock:
            cursor.execute("DELETE FROM logs")
            conn.commit()
    except Exception as e:
        logger.warning("Failed to clear logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to clear DB logs")
    return {"detail": "All logs cleared"}

@app.post("/update_mode")
async def update_mode(mode_data: ModeUpdate, request: Request):
    require_admin_key(request)
    logger.info("Compliance mode updated to: %s", mode_data.mode)
    return {"message": f"Mode successfully updated to {mode_data.mode}"}

@app.get("/get_settings")
async def get_settings_endpoint(request: Request):
    require_admin_key(request)
    return settings

@app.get("/health")
async def healthcheck():
    return {
        "status": "ok",
        "nlp_models_loaded": nlp_engine_loaded,
        "gemini_enabled": bool(GEMINI_API_KEY),
    }

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)
