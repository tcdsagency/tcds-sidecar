# TCDS Sidecar Service

Python service for browser automation and token extraction. Runs alongside TCDS-Triage.

## What It Does

| Endpoint | Purpose |
|----------|---------|
| `POST /agencyzoom/session` | Get session cookies + CSRF token for SMS |
| `POST /rpr/token` | Get JWT token for property data |
| `POST /mmi/token` | Get bearer token for market data |
| `POST /delphi/chat` | Chat with Delphi AI assistant |
| `POST /delphi/initialize` | Initialize Delphi browser session |
| `GET /health` | Health check |

## Deploy to Railway (5 minutes)

### Step 1: Create Railway Account
Go to https://railway.app and sign up with GitHub

### Step 2: Create New Project
1. Click **New Project**
2. Click **Deploy from GitHub repo**
3. Connect your GitHub account if needed
4. Select this repository (or upload it first)

### Step 3: Add Environment Variables
In Railway dashboard, go to your service → **Variables** tab:

```
AGENCYZOOM_EMAIL=service@tcdsagency.com
AGENCYZOOM_PASSWORD=Welcome2023!
RPR_EMAIL=your-rpr-email
RPR_PASSWORD=your-rpr-password
MMI_EMAIL=your-mmi-email
MMI_PASSWORD=your-mmi-password
DELPHI_USERNAME=tconn
DELPHI_PASSWORD=your-delphi-password
```

### Step 4: Deploy
Railway will automatically build and deploy. Takes ~3-5 minutes.

### Step 5: Get Your URL
Once deployed, click **Settings** → copy your **Railway URL** (like `tcds-sidecar-production.up.railway.app`)

### Step 6: Update TCDS-Triage
Add this to your `.env.local`:
```
SIDECAR_URL=https://your-railway-url.up.railway.app
```

---

## Local Development

### Prerequisites
- Python 3.11+
- Playwright browsers

### Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy environment file
cp .env.example .env
# Edit .env with your credentials

# Run server
uvicorn app.main:app --reload --port 8000
```

### Test Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Get AgencyZoom session (takes ~10-20 seconds)
curl -X POST http://localhost:8000/agencyzoom/session

# Get RPR token
curl -X POST http://localhost:8000/rpr/token

# Initialize Delphi (do this first)
curl -X POST http://localhost:8000/delphi/initialize

# Chat with Delphi
curl -X POST http://localhost:8000/delphi/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is an umbrella policy?"}'
```

---

## API Reference

### POST /agencyzoom/session
Get session cookies for AgencyZoom SMS API.

**Query params:**
- `force_refresh=true` - Skip cache

**Response:**
```json
{
  "success": true,
  "data": {
    "cookies": [...],
    "csrfToken": "abc123"
  },
  "fromCache": false,
  "expiresAt": "2024-01-06T12:00:00"
}
```

### POST /rpr/token
Get JWT token for RPR property API.

**Response:**
```json
{
  "success": true,
  "data": {
    "token": "eyJ..."
  },
  "fromCache": false,
  "expiresAt": "2024-01-05T13:00:00"
}
```

### POST /delphi/chat
Chat with Delphi AI. Must call `/delphi/initialize` first.

**Body:**
```json
{
  "message": "What is umbrella insurance?"
}
```

**Response:**
```json
{
  "success": true,
  "question": "What is umbrella insurance?",
  "answer": "Umbrella insurance is a type of...",
  "timestamp": "2024-01-05T12:00:00"
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    TCDS-Triage (Next.js)               │
│                      Vercel / Local                     │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────┐
│                  TCDS Sidecar (FastAPI)                │
│                      Railway                            │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ AgencyZoom  │  │    RPR      │  │    MMI      │     │
│  │ Extractor   │  │ Extractor   │  │ Extractor   │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         └────────────────┼────────────────┘             │
│                          │                              │
│                    Playwright                           │
│                    (Chromium)                           │
└─────────────────────────────────────────────────────────┘
```

## Token Caching

Tokens are cached in memory:
- AgencyZoom: 23 hours
- RPR: 1 hour
- MMI: 23 hours

Use `?force_refresh=true` to bypass cache.

---

Built for TCDS Insurance 🏠
