# Prompt Compliance Automation

Prompt Compliance Automation is a FastAPI-based middleware service that screens LLM prompts for policy violations before they reach a model endpoint. It detects sensitive keywords, PII, and toxic content, then classifies each prompt as Safe, Flagged, or Blocked.

## Core Capabilities

- Real-time prompt analysis and classification
- Keyword policy checks (flagged and blocked terms)
- PII detection and redaction via Presidio
- Toxicity scoring via Detoxify thresholds
- Configurable policy settings in settings.json
- Audit logging in SQLite
- Web dashboard for analysis and log review
- Security headers, trusted-host checks, and response compression

## Architecture

1. User submits prompt to FastAPI endpoint
2. Service runs keyword, PII, and toxicity checks
3. Prompt is classified and optionally redacted
4. Result is logged to SQLite for auditability
5. Safe prompts can be forwarded to Gemini for response generation

## Project Layout

- app.py: FastAPI service and moderation pipeline
- index.html: Web dashboard
- clear_db.py: Utility to clear SQLite logs
- settings.json: Policy and threshold configuration
- requirements.txt: Pinned project dependencies
- .env.example: Environment variable template
- images/: Screenshots and assets

## Setup

### 1) Create and activate a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3) Configure environment variables

Create a .env file in the project root:

```env
GEMINI_API_KEY=your_google_api_key
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
TRUSTED_HOSTS=127.0.0.1,localhost
```

## Run

```bash
uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000 in a browser.

## API Endpoints

- POST /check_prompt: Analyze a prompt and return classification details
- GET /get_logs: Retrieve log history
- GET /get_logs?limit=200&offset=0&status=Blocked: Paginated and filterable logs
	Response includes logs, total, limit, and offset.
- POST /clear_logs: Delete all audit logs
- POST /update_mode: Update moderation mode label
- GET /get_settings: Return active policy configuration
- GET /health: Service health and model availability

## Security Notes

- Do not commit API keys or tokens to repository files
- Keep .env local and excluded from source control
- Restrict CORS origins in ALLOWED_ORIGINS for production
- Rotate any key that has ever been committed

## License

MIT
