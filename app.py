import sqlite3
import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import functools
from contextlib import asynccontextmanager
import google.generativeai as genai
import os
from fastapi.middleware.cors import CORSMiddleware
from playsound import playsound
import threading

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# --- ENV VARIABLES ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALERT_PII_PATH = os.getenv("ALERT_PII_PATH")
ALERT_POLICY_PATH = os.getenv("ALERT_POLICY_PATH")


def play_alert(file_path: str):
    """Play alert sound in a separate thread so it doesn't block FastAPI."""
    try:
        threading.Thread(target=playsound, args=(file_path,), daemon=True).start()
        print(f"🔊 Playing alert: {file_path}")
    except Exception as e:
        print(f"❌ Failed to play sound {file_path}: {e}")


# NLP/ML Libraries
import spacy
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from detoxify import Detoxify

# --- Setup and Initialization ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to handle startup/shutdown gracefully."""
    print("🚀 Starting app and loading ML models...")

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("✅ Gemini API configured successfully from .env")
    except Exception as e:
        print(f"❌ Error configuring Gemini API: {e}")

    yield
    print("🛑 Shutting down app. Closing DB connection...")
    try:
        conn.close()
        print("✅ Database connection closed")
    except Exception as e:
        print(f"⚠️ Error closing DB connection: {e}")


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print("🌐 CORS middleware added")

# Mount static files
app.mount("/static", StaticFiles(directory="."), name="static")
print("📁 Static files mounted at /static")

# --- Load settings ---
settings = {}
try:
    with open("settings.json", "r") as f:
        settings = json.load(f)
        print("⚙️ Settings loaded from settings.json")
except (FileNotFoundError, json.JSONDecodeError):
    print("⚠️ settings.json not found or invalid, using defaults.")
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
        "max_payload_size": 10240
    }

# Extract settings
TOXICITY_THRESHOLDS = settings["toxicity_thresholds"]
FLAGGED_KEYWORDS = [kw.lower() for kw in settings.get("flagged_keywords", [])]
BLOCKED_KEYWORDS = [kw.lower() for kw in settings.get("blocked_keywords", [])]
MAX_PROMPT_LENGTH = settings["max_prompt_length"]
MAX_PAYLOAD_SIZE = settings["max_payload_size"]

# --- Initialize NLP/ML Models ---
nlp_engine_loaded = False
try:
    nlp = spacy.load("en_core_web_sm")
    print("✅ SpaCy NLP model loaded")

    analyzer = AnalyzerEngine()
    detoxify_model = Detoxify('original')
    print("✅ Detoxify model loaded")

    # Custom ATM PIN recognizer
    atm_pin_pattern = Pattern(name="ATM_PIN", regex=r"\b\d{4,6}\b", score=0.85)
    atm_pin_recognizer = PatternRecognizer(
        supported_entity="ATM_PIN",
        patterns=[atm_pin_pattern]
    )
    analyzer.registry.add_recognizer(atm_pin_recognizer)
    nlp_engine_loaded = True
    print("✅ Presidio Analyzer initialized with custom ATM PIN recognizer")
except Exception as e:
    print(f"❌ Error loading NLP/ML models: {e}")
    detoxify_model = None

# --- Connect to SQLite ---
conn = sqlite3.connect('logs.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        reasons TEXT,
        timestamp TEXT NOT NULL,
        redacted_prompt TEXT,
        gemini_response TEXT
    )
''')
conn.commit()
print("🗄️ SQLite database connected and logs table ensured")

# --- In-memory logs ---
logs = []

# --- Data Models ---
class Prompt(BaseModel):
    text: str

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
    mode: str

# --- Helper Functions ---
def get_gemini_response(prompt: str) -> Optional[str]:
    """Get response from Gemini API for safe prompts"""
    try:
        print("💬 Sending prompt to Gemini API...")
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        gemini_text = response.text
        print(f"💡 Gemini response:\n{gemini_text}")
        return gemini_text
    except Exception as e:
        print(f"❌ Error getting Gemini response: {e}")
        return f"Error getting response from Gemini API: {str(e)}"


@functools.lru_cache(maxsize=128)
def analyze_prompt(prompt: str) -> Dict[str, Any]:
    print(f"🔍 Analyzing prompt: {prompt[:50]}...")
    status = "Safe"
    reasons = []
    redacted_prompt = prompt
    gemini_response = None

    if len(prompt) > MAX_PROMPT_LENGTH:
        reasons.append({"type": "warning", "message": f"Prompt length exceeds {MAX_PROMPT_LENGTH} chars."})
        print("⚠️ Prompt exceeds maximum length")

    if not nlp_engine_loaded:
        reasons.append({"type": "error", "message": "ML/NLP models failed to load."})
        print("❌ ML/NLP models not loaded")
        return {"status": "Flagged", "reasons": reasons, "redacted_prompt": redacted_prompt, "gemini_response": gemini_response}

    # Keyword checks
    lower_text = prompt.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in lower_text:
            reasons.append({"type": "blocked", "message": f"Blocked keyword detected: {kw}"})
            status = "Blocked"
            print(f"⛔ Blocked keyword detected: {kw}")

    for kw in FLAGGED_KEYWORDS:
        if kw in lower_text and status == "Safe":
            reasons.append({"type": "flagged", "message": f"Flagged keyword detected: {kw}"})
            status = "Flagged"
            print(f"⚠️ Flagged keyword detected: {kw}")

    # PII detection
    try:
        results = analyzer.analyze(text=prompt, language="en")
        if results:
            pii_entities = sorted(list(set([res.entity_type for res in results])))
            if pii_entities:
                reasons.append({"type": "pii", "message": f"Contains PII: {', '.join(pii_entities)}."})
                print(f"🛡️ PII detected: {pii_entities}")
                for res in reversed(results):
                    redacted_prompt = redacted_prompt[:res.start] + f"[{res.entity_type}]" + redacted_prompt[res.end:]
                if any(ent in pii_entities for ent in ["PHONE_NUMBER", "CREDIT_CARD", "ATM_PIN"]):
                    status = "Blocked"
    except Exception as e:
        reasons.append({"type": "error", "message": "PII analysis failed."})
        print(f"❌ PII analysis failed: {e}")

    # Toxicity detection
    if detoxify_model:
        try:
            tox_results = detoxify_model.predict(prompt)
            for label, score in tox_results.items():
                if label in TOXICITY_THRESHOLDS:
                    threshold = TOXICITY_THRESHOLDS[label]
                    if score > threshold:
                        reasons.append({"type": "toxic", "message": f"Detected '{label}' with score {score:.2f}."})
                        print(f"☣️ Toxicity detected: {label} score={score:.2f}")
                        if label in ["severe_toxicity", "threat"]:
                            status = "Blocked"
                        elif status == "Safe":
                            status = "Flagged"
        except Exception as e:
            reasons.append({"type": "error", "message": "Toxicity analysis failed."})
            print(f"❌ Toxicity analysis failed: {e}")

    # Audio alerts
    if status == "Blocked":
        if any(r["type"] == "pii" for r in reasons):
            play_alert(ALERT_PII_PATH)
        else:
            play_alert(ALERT_POLICY_PATH)
    elif status == "Flagged":
        play_alert(ALERT_POLICY_PATH)

    # Gemini response if safe
    if status == "Safe" and prompt.strip():
        print(f"💡 Prompt is safe, sending to Gemini for response...")
        gemini_response = get_gemini_response(prompt)

    print(f"✅ Analysis complete. Status: {status}")
    return {
        "status": status,
        "reasons": reasons,
        "redacted_prompt": redacted_prompt if redacted_prompt != prompt else None,
        "gemini_response": gemini_response
    }


def log_result(prompt: str, status: str, reasons: List[Dict[str, str]], redacted_prompt: Optional[str], gemini_response: Optional[str]):
    try:
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO logs (prompt, status, reasons, timestamp, redacted_prompt, gemini_response) VALUES (?, ?, ?, ?, ?, ?)",
            (prompt, status, json.dumps(reasons), timestamp, redacted_prompt, gemini_response)
        )
        conn.commit()
        logs.append({
            "prompt": prompt,
            "status": status,
            "reasons": reasons,
            "redacted_prompt": redacted_prompt,
            "gemini_response": gemini_response,
            "timestamp": timestamp
        })
        print(f"📝 Logged prompt to DB. Status: {status}")
    except Exception as e:
        print(f"❌ Failed to log to DB: {e}")


# --- API Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    print("📄 Serving index.html")
    with open("index.html", "r") as f:
        return f.read()

@app.post("/check_prompt")
async def check_prompt_endpoint(prompt_data: Prompt, request: Request) -> AnalysisResult:
    content_length = request.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_PAYLOAD_SIZE:
        print(f"⚠️ Payload too large: {content_length} bytes")
        raise HTTPException(status_code=413, detail="Request payload size exceeds limit.")
    
    result = analyze_prompt(prompt_data.text)
    log_result(prompt_data.text, result["status"], result["reasons"], result.get("redacted_prompt"), result.get("gemini_response"))
    
    return AnalysisResult(
        prompt=prompt_data.text,
        status=result["status"],
        reasons=result["reasons"],
        redacted_prompt=result.get("redacted_prompt"),
        gemini_response=result.get("gemini_response")
    )

@app.get("/get_logs")
async def get_logs_endpoint():
    print("📊 Fetching logs from DB")
    try:
        cursor.execute("SELECT id, prompt, status, reasons, timestamp, redacted_prompt, gemini_response FROM logs ORDER BY id DESC")
        logs_list = [
            {
                "id": e[0], 
                "prompt": e[1], 
                "status": e[2], 
                "reasons": json.loads(e[3]),
                "timestamp": e[4], 
                "redacted_prompt": e[5],
                "gemini_response": e[6]
            } for e in cursor.fetchall()
        ]
        print(f"✅ {len(logs_list)} logs fetched")
        return {"logs": logs_list}
    except Exception as e:
        print(f"❌ Failed to fetch logs: {e}")
        return {"logs": []}

@app.post("/clear_logs")
async def clear_logs():
    global logs
    logs = []
    try:
        cursor.execute("DELETE FROM logs")
        conn.commit()
        print("🧹 All logs cleared")
    except Exception as e:
        print(f"❌ Failed to clear DB logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear DB logs")
    return {"detail": "All logs cleared"}

@app.post("/update_mode")
async def update_mode(mode_data: ModeUpdate):
    print(f"⚙️ Compliance mode updated to: {mode_data.mode}")
    return {"message": f"Mode successfully updated to {mode_data.mode}"}

@app.get("/get_settings")
async def get_settings_endpoint():
    print("⚙️ Returning current settings")
    return settings

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return ""
