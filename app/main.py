"""
TCDS Sidecar Service
====================
Unified Python service for browser automation and token extraction.

Endpoints:
- POST /agencyzoom/session  - Get AgencyZoom cookies + CSRF token
- POST /agencyzoom/sms      - Send SMS via AgencyZoom browser automation
- POST /rpr/token           - Get RPR JWT token
- POST /mmi/token           - Get MMI bearer token
- POST /delphi/chat         - Chat with Delphi AI
- POST /delphi/initialize   - Initialize Delphi browser
- GET  /health              - Health check
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import our extractors
from app.extractors.agencyzoom import AgencyZoomExtractor
from app.extractors.rpr import RPRExtractor
from app.extractors.mmi import MMIExtractor
from app.extractors.delphi import DelphiProxy


# ============================================================================
# MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str

class SMSRequest(BaseModel):
    phone_number: str
    message: str

class SMSResponse(BaseModel):
    success: bool
    error: Optional[str] = None

class TokenResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    fromCache: bool = False
    expiresAt: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str
    extractors: Dict[str, bool]


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Token cache with TTLs
token_cache: Dict[str, Dict[str, Any]] = {}

# Extractor instances
agencyzoom_extractor: Optional[AgencyZoomExtractor] = None
rpr_extractor: Optional[RPRExtractor] = None
mmi_extractor: Optional[MMIExtractor] = None
delphi_proxy: Optional[DelphiProxy] = None


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize extractors on startup, cleanup on shutdown"""
    global agencyzoom_extractor, rpr_extractor, mmi_extractor, delphi_proxy
    
    print("🚀 Starting TCDS Sidecar Service...")
    
    # Initialize extractors (they lazy-load browsers)
    agencyzoom_extractor = AgencyZoomExtractor()
    rpr_extractor = RPRExtractor()
    mmi_extractor = MMIExtractor()
    delphi_proxy = DelphiProxy()
    
    print("✅ Extractors initialized")
    
    yield
    
    # Cleanup
    print("🛑 Shutting down...")
    if delphi_proxy:
        await delphi_proxy.close()
    print("✅ Cleanup complete")


# ============================================================================
# APP
# ============================================================================

app = FastAPI(
    title="TCDS Sidecar",
    description="Browser automation service for token extraction",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# CACHE HELPERS
# ============================================================================

def get_cached(key: str) -> Optional[Dict[str, Any]]:
    """Get cached token if not expired"""
    if key in token_cache:
        cached = token_cache[key]
        if datetime.fromisoformat(cached["expiresAt"]) > datetime.now():
            return cached
        del token_cache[key]
    return None

def set_cached(key: str, data: Dict[str, Any], ttl_hours: int = 23):
    """Cache token with TTL"""
    expires = datetime.now() + timedelta(hours=ttl_hours)
    token_cache[key] = {
        **data,
        "expiresAt": expires.isoformat()
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        service="tcds-sidecar",
        timestamp=datetime.now().isoformat(),
        extractors={
            "agencyzoom": agencyzoom_extractor is not None,
            "rpr": rpr_extractor is not None,
            "mmi": mmi_extractor is not None,
            "delphi": delphi_proxy is not None and delphi_proxy.is_initialized,
        }
    )


@app.post("/agencyzoom/session", response_model=TokenResponse)
async def get_agencyzoom_session(force_refresh: bool = False):
    """
    Get AgencyZoom session cookies and CSRF token.
    Required for SMS endpoint which rejects JWT tokens.
    """
    cache_key = "agencyzoom"

    # Check cache
    if not force_refresh:
        cached = get_cached(cache_key)
        if cached:
            return TokenResponse(
                success=True,
                data=cached,
                fromCache=True,
                expiresAt=cached["expiresAt"]
            )

    # Extract fresh session
    try:
        result = await agencyzoom_extractor.extract()
        if result.get("success"):
            set_cached(cache_key, result)
            return TokenResponse(
                success=True,
                data=result,
                fromCache=False,
                expiresAt=token_cache[cache_key]["expiresAt"]
            )
        else:
            return TokenResponse(
                success=False,
                error=result.get("error", "Unknown error")
            )
    except Exception as e:
        return TokenResponse(success=False, error=str(e))


@app.post("/agencyzoom/sms", response_model=SMSResponse)
async def send_agencyzoom_sms(request: SMSRequest):
    """
    Send SMS via AgencyZoom using HTTP API with session cookies.
    """
    try:
        print(f"[SMS] Sending to {request.phone_number}: {request.message[:50]}...")

        # Prime extractor's cache from our token_cache if available
        cached = get_cached("agencyzoom")
        if cached and cached.get("cookies"):
            agencyzoom_extractor._cached_cookies = cached.get("cookies")
            agencyzoom_extractor._cached_csrf = cached.get("csrfToken")
            print("[SMS] Using cached session")

        result = await agencyzoom_extractor.send_sms(
            phone_number=request.phone_number,
            message=request.message
        )
        return SMSResponse(
            success=result.get("success", False),
            error=result.get("error")
        )
    except Exception as e:
        print(f"[SMS] Error: {e}")
        return SMSResponse(success=False, error=str(e))


@app.post("/rpr/token", response_model=TokenResponse)
async def get_rpr_token(force_refresh: bool = False):
    """
    Get RPR JWT token for property data API.
    Token is extracted from browser localStorage after login.
    """
    cache_key = "rpr"
    
    if not force_refresh:
        cached = get_cached(cache_key)
        if cached:
            return TokenResponse(
                success=True,
                data=cached,
                fromCache=True,
                expiresAt=cached["expiresAt"]
            )
    
    try:
        result = await rpr_extractor.extract()
        if result.get("token"):
            data = {"token": result["token"]}
            set_cached(cache_key, data, ttl_hours=1)  # RPR tokens expire faster
            return TokenResponse(
                success=True,
                data=data,
                fromCache=False,
                expiresAt=token_cache[cache_key]["expiresAt"]
            )
        else:
            return TokenResponse(
                success=False,
                error=result.get("error", "Could not extract token")
            )
    except Exception as e:
        return TokenResponse(success=False, error=str(e))


@app.post("/mmi/token", response_model=TokenResponse)
async def get_mmi_token(force_refresh: bool = False):
    """
    Get MMI bearer token for property history API.
    Extracts session cookies after browser login.
    """
    cache_key = "mmi"
    
    if not force_refresh:
        cached = get_cached(cache_key)
        if cached:
            return TokenResponse(
                success=True,
                data=cached,
                fromCache=True,
                expiresAt=cached["expiresAt"]
            )
    
    try:
        result = await mmi_extractor.extract()
        if result.get("success"):
            set_cached(cache_key, result)
            return TokenResponse(
                success=True,
                data=result,
                fromCache=False,
                expiresAt=token_cache[cache_key]["expiresAt"]
            )
        else:
            return TokenResponse(
                success=False,
                error=result.get("error", "Could not extract token")
            )
    except Exception as e:
        return TokenResponse(success=False, error=str(e))


@app.post("/delphi/initialize")
async def initialize_delphi():
    """Initialize Delphi browser session"""
    try:
        username = os.getenv("DELPHI_USERNAME", "tconn")
        password = os.getenv("DELPHI_PASSWORD", "")
        
        if not password:
            raise HTTPException(400, "DELPHI_PASSWORD not configured")
        
        await delphi_proxy.initialize(username, password)
        
        return {
            "success": True,
            "message": "Delphi initialized",
            "authenticated": delphi_proxy.authenticated
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/delphi/chat")
async def chat_with_delphi(request: ChatRequest):
    """Send a message to Delphi AI and get response"""
    if not delphi_proxy or not delphi_proxy.is_initialized:
        raise HTTPException(503, "Delphi not initialized. Call /delphi/initialize first.")
    
    try:
        response = await delphi_proxy.send_message(request.message)
        return {
            "success": True,
            "question": request.message,
            "answer": response,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/delphi/status")
async def delphi_status():
    """Get Delphi proxy status"""
    return {
        "initialized": delphi_proxy.is_initialized if delphi_proxy else False,
        "authenticated": delphi_proxy.authenticated if delphi_proxy else False,
        "lastActivity": delphi_proxy.last_activity if delphi_proxy else None
    }


@app.post("/cache/clear")
async def clear_cache():
    """Clear all cached tokens"""
    global token_cache
    token_cache = {}
    return {"success": True, "message": "Cache cleared"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
