import sqlite3
import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import functools
# NEW: Import for CORS
from fastapi.middleware.cors import CORSMiddleware


# NLP/ML Libraries
import spacy
from presidio_analyzer import AnalyzerEngine
from detoxify import Detoxify
import torch

# --- Setup and Initialization ---

app = FastAPI()

# NEW: Add CORS middleware to allow requests from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for simplicity, can be restricted
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)


# Mount the static files (like index.html)
app.mount("/static", StaticFiles(directory="."), name="static")

# Load settings from a JSON file for configurability
settings = {}
try:
    with open("settings.json", "r") as f:
        settings = json.load(f)
except FileNotFoundError:
    print("settings.json not found. Using default settings.")
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
        "max_prompt_length": 512,
        "max_payload_size": 10240  # 10 KB in bytes
    }
except json.JSONDecodeError:
    print("Invalid JSON in settings.json. Using default settings.")
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
        "max_prompt_length": 512,
        "max_payload_size": 10240  # 10 KB in bytes
    }


# Initialize NLP/ML Models and Components
nlp_engine_loaded = False
try:
    # spaCy for basic NLP and keyword matching
    nlp = spacy.load("en_core_web_sm")
    
    # Presidio for PII detection
    analyzer = AnalyzerEngine()
    
    # Detoxify for toxicity and offensive content
    detoxify_model = Detoxify('original')
    nlp_engine_loaded = True
    print("All ML models loaded successfully.")
except Exception as e:
    print(f"Error loading models: {e}")
    # Fallback or error handling for model loading failures
    detoxify_model = None


# Connect to SQLite database
conn = sqlite3.connect('logs.db', check_same_thread=False)
cursor = conn.cursor()

# Create logs table if it doesn't exist
# MODIFIED: Added redacted_prompt column
cursor.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        reasons TEXT,
        timestamp TEXT NOT NULL,
        redacted_prompt TEXT
    )
''')
# Add redacted_prompt column if it doesn't exist for backward compatibility
try:
    cursor.execute("ALTER TABLE logs ADD COLUMN redacted_prompt TEXT;")
    conn.commit()
    print("Added 'redacted_prompt' column to logs table.")
except sqlite3.OperationalError:
    # Column already exists, which is fine
    pass

conn.commit()

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

# NEW: Model for mode update
class ModeUpdate(BaseModel):
    mode: str

# --- Helper Functions ---

@functools.lru_cache(maxsize=128)
def analyze_prompt(prompt: str) -> Dict[str, Any]:
    """
    Performs a series of checks on the input prompt.
    Returns the status, a list of reasons, and a redacted version of the prompt.
    """
    status = "Safe"
    reasons = []
    redacted_prompt = prompt
    
    if len(prompt) > settings["max_prompt_length"]:
        reasons.append({"type": "warning", "message": f"Prompt length exceeds recommended limit of {settings['max_prompt_length']} characters. Result may be less accurate."})

    if not nlp_engine_loaded:
        reasons.append({"type": "error", "message": "ML/NLP models failed to load. Only keyword checks are active."})
        return {"status": "Flagged", "reasons": reasons, "redacted_prompt": redacted_prompt}

    # 1. Rule-Based Check (Simple Keyword/Regex)
    keywords = settings.get("flagged_keywords", [])
    if any(keyword in prompt.lower() for keyword in keywords):
        reasons.append({"type": "keyword", "message": "Contains a flagged keyword."})
        status = "Flagged"

    # 2. PII Detection (using Presidio)
    try:
        results = analyzer.analyze(text=prompt, language="en")
        if results:
            pii_entities = sorted(list(set([res.entity_type for res in results])))
            reasons.append({"type": "pii", "message": f"Contains Personal Identifiable Information (PII): {', '.join(pii_entities)}."})
            
            # Redact the prompt
            redacted_prompt = prompt
            for res in reversed(results): # Reverse to avoid index shifting
                redacted_prompt = redacted_prompt[:res.start] + f"[{res.entity_type}]" + redacted_prompt[res.end:]
            
            if "PHONE_NUMBER" in pii_entities or "CREDIT_CARD" in pii_entities:
                if status != "Blocked":
                    status = "Blocked"
            else:
                if status == "Safe":
                    status = "Flagged"
    except Exception as e:
        print(f"Error during PII analysis: {e}")
        reasons.append({"type": "error", "message": "PII analysis failed."})

    # 3. Toxicity/Hate Speech Detection (using Detoxify)
    if detoxify_model:
        try:
            results = detoxify_model.predict(prompt)
            
            for label, score in results.items():
                if label in settings["toxicity_thresholds"]:
                    threshold = settings["toxicity_thresholds"][label]
                    if score > threshold:
                        reasons.append({"type": "toxic", "message": f"Detected '{label}' with score {score:.2f}."})
                        if label == "severe_toxicity" or label == "threat":
                            if status != "Blocked":
                                status = "Blocked"
                        else:
                            if status == "Safe":
                                status = "Flagged"
        except Exception as e:
            print(f"Error during toxicity analysis: {e}")
            reasons.append({"type": "error", "message": "Toxicity analysis failed."})

    return {"status": status, "reasons": reasons, "redacted_prompt": redacted_prompt if redacted_prompt != prompt else None}

def log_result(prompt: str, status: str, reasons: List[Dict[str, str]], redacted_prompt: Optional[str]):
    """Logs the result of the prompt check to the database."""
    try:
        timestamp = datetime.now().isoformat()
        reasons_str = json.dumps(reasons)
        cursor.execute(
            "INSERT INTO logs (prompt, status, reasons, timestamp, redacted_prompt) VALUES (?, ?, ?, ?, ?)",
            (prompt, status, reasons_str, timestamp, redacted_prompt)
        )
        conn.commit()
    except Exception as e:
        print(f"Failed to log to database: {e}")

# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serves the main HTML page."""
    with open("index.html", "r") as f:
        return f.read()

@app.post("/check_prompt")
async def check_prompt_endpoint(prompt_data: Prompt, request: Request) -> AnalysisResult:
    """
    API endpoint to receive a prompt, analyze it, and return the result.
    Checks for maximum payload size to prevent abuse.
    """
    # Check for max payload size
    content_length = request.headers.get("Content-Length")
    if content_length and int(content_length) > settings.get("max_payload_size", 10240):
        raise HTTPException(status_code=413, detail=f"Request payload size exceeds the maximum limit of {settings.get('max_payload_size', 10240)} bytes.")

    analysis_result = analyze_prompt(prompt_data.text)
    
    # Log the result before sending the response
    log_result(prompt_data.text, analysis_result["status"], analysis_result["reasons"], analysis_result.get("redacted_prompt"))
    
    return AnalysisResult(
        prompt=prompt_data.text,
        status=analysis_result["status"],
        reasons=analysis_result["reasons"],
        redacted_prompt=analysis_result.get("redacted_prompt")
    )

@app.get("/get_logs")
async def get_logs_endpoint():
    """
    API endpoint to retrieve all logged prompt checks.
    """
    try:
        # MODIFIED: Select new redacted_prompt column
        cursor.execute("SELECT id, prompt, status, reasons, timestamp, redacted_prompt FROM logs ORDER BY id DESC")
        log_entries = cursor.fetchall()
        
        # Convert the fetched data into a list of dictionaries for JSON response
        logs_list = []
        for entry in log_entries:
            logs_list.append({
                "id": entry[0],
                "prompt": entry[1],
                "status": entry[2],
                "reasons": json.loads(entry[3]),
                "timestamp": entry[4],
                "redacted_prompt": entry[5]
            })
            
        return {"logs": logs_list}
    except Exception as e:
        print(f"Failed to retrieve logs: {e}")
        return {"logs": []}

# NEW: Endpoint to handle mode updates
@app.post("/update_mode")
async def update_mode(mode_data: ModeUpdate):
    """
    API endpoint to update the current operational mode.
    In a real application, this would change server-side behavior.
    """
    mode = mode_data.mode
    # For now, we just print it to the console.
    print(f"Compliance mode updated to: {mode}")
    # You could store this in a global variable or a settings file.
    return {"message": f"Mode successfully updated to {mode}"}


@app.get("/get_settings")
async def get_settings_endpoint():
    """
    API endpoint to retrieve current settings for the frontend.
    """
    return settings

# Simple route to serve the favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return ""

