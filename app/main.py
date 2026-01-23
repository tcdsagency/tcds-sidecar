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
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional, Dict, Any, List, Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import aiohttp

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


class AlertCustomer(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class AlertProperty(BaseModel):
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    price: Optional[float] = None
    link: Optional[str] = None


class AlertRequest(BaseModel):
    alert_type: str
    summary: str
    customer: AlertCustomer
    property: AlertProperty
    notification_channels: Optional[List[Literal["email", "slack"]]] = None
    crm_task: bool = False
    metadata: Optional[Dict[str, Any]] = None


class AlertStatusUpdate(BaseModel):
    status: Literal["reviewed", "contacted"]
    staff_member: Optional[str] = None
    note: Optional[str] = None


class AlertResponse(BaseModel):
    id: str
    created_at: str
    alert_type: str
    summary: str
    customer: AlertCustomer
    property: AlertProperty
    metadata: Optional[Dict[str, Any]] = None
    delivery: Dict[str, Any]
    reviewed_at: Optional[str] = None
    contacted_at: Optional[str] = None
    staff_notes: Optional[List[Dict[str, Any]]] = None


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Token cache with TTLs
token_cache: Dict[str, Dict[str, Any]] = {}
alert_store: Dict[str, Dict[str, Any]] = {}

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


def build_alert_message(alert: AlertRequest) -> str:
    property_parts = [alert.property.address]
    if alert.property.city:
        property_parts.append(alert.property.city)
    if alert.property.state:
        property_parts.append(alert.property.state)
    if alert.property.postal_code:
        property_parts.append(alert.property.postal_code)
    property_line = ", ".join(property_parts)
    price_line = f"${alert.property.price:,.0f}" if alert.property.price else "N/A"
    link_line = alert.property.link or "N/A"
    customer_email = alert.customer.email or "N/A"
    customer_phone = alert.customer.phone or "N/A"

    return (
        f"New Alert: {alert.alert_type}\n"
        f"Summary: {alert.summary}\n\n"
        f"Customer: {alert.customer.name}\n"
        f"Email: {customer_email}\n"
        f"Phone: {customer_phone}\n\n"
        "Property:\n"
        f"{property_line}\n"
        f"Price: {price_line}\n"
        f"Link: {link_line}\n"
    )


async def send_email_notification(subject: str, body: str) -> Dict[str, Any]:
    host = os.getenv("ALERT_EMAIL_HOST")
    port = int(os.getenv("ALERT_EMAIL_PORT", "587"))
    username = os.getenv("ALERT_EMAIL_USERNAME")
    password = os.getenv("ALERT_EMAIL_PASSWORD")
    from_email = os.getenv("ALERT_EMAIL_FROM")
    to_emails = os.getenv("ALERT_EMAIL_TO", "")
    recipients = [email.strip() for email in to_emails.split(",") if email.strip()]

    if not host or not from_email or not recipients:
        return {"sent": False, "error": "Email configuration incomplete"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    def _send():
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)

    await asyncio.to_thread(_send)
    return {"sent": True, "recipients": recipients}


async def send_slack_notification(body: str) -> Dict[str, Any]:
    webhook_url = os.getenv("ALERT_SLACK_WEBHOOK")
    if not webhook_url:
        return {"sent": False, "error": "Slack webhook not configured"}
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json={"text": body}) as response:
            if response.status >= 300:
                return {
                    "sent": False,
                    "error": f"Slack webhook failed with {response.status}"
                }
            return {"sent": True}


async def create_crm_task(alert: AlertRequest) -> Dict[str, Any]:
    webhook_url = os.getenv("ALERT_CRM_WEBHOOK")
    if not webhook_url:
        return {"created": False, "error": "CRM webhook not configured"}
    payload = {
        "type": alert.alert_type,
        "summary": alert.summary,
        "customer": alert.customer.model_dump(),
        "property": alert.property.model_dump(),
        "metadata": alert.metadata or {},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json=payload) as response:
            if response.status >= 300:
                return {
                    "created": False,
                    "error": f"CRM webhook failed with {response.status}"
                }
            return {"created": True}


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


@app.post("/alerts", response_model=AlertResponse)
async def create_alert(request: AlertRequest, background_tasks: BackgroundTasks):
    alert_id = f"alert-{len(alert_store) + 1}"
    created_at = datetime.now().isoformat()
    message_body = build_alert_message(request)
    subject = f"[Alert] {request.alert_type} - {request.customer.name}"

    delivery_result: Dict[str, Any] = {"email": None, "slack": None, "crm": None}
    channels = request.notification_channels
    if channels is None:
        channels = []
        if os.getenv("ALERT_EMAIL_TO"):
            channels.append("email")
        if os.getenv("ALERT_SLACK_WEBHOOK"):
            channels.append("slack")

    async def _deliver():
        if "email" in channels:
            try:
                delivery_result["email"] = await send_email_notification(
                    subject=subject,
                    body=message_body
                )
            except Exception as exc:
                delivery_result["email"] = {"sent": False, "error": str(exc)}
        if "slack" in channels:
            try:
                delivery_result["slack"] = await send_slack_notification(message_body)
            except Exception as exc:
                delivery_result["slack"] = {"sent": False, "error": str(exc)}
        if request.crm_task:
            try:
                delivery_result["crm"] = await create_crm_task(request)
            except Exception as exc:
                delivery_result["crm"] = {"created": False, "error": str(exc)}

    background_tasks.add_task(_deliver)

    alert_record = {
        "id": alert_id,
        "created_at": created_at,
        "alert_type": request.alert_type,
        "summary": request.summary,
        "customer": request.customer,
        "property": request.property,
        "metadata": request.metadata,
        "delivery": delivery_result,
        "reviewed_at": None,
        "contacted_at": None,
        "staff_notes": []
    }
    alert_store[alert_id] = alert_record

    return AlertResponse(
        id=alert_id,
        created_at=created_at,
        alert_type=request.alert_type,
        summary=request.summary,
        customer=request.customer,
        property=request.property,
        metadata=request.metadata,
        delivery=delivery_result,
        reviewed_at=None,
        contacted_at=None,
        staff_notes=[]
    )


@app.get("/staff/alerts", response_model=List[AlertResponse])
async def list_alerts():
    alerts = []
    for alert in alert_store.values():
        alerts.append(AlertResponse(
            id=alert["id"],
            created_at=alert["created_at"],
            alert_type=alert["alert_type"],
            summary=alert["summary"],
            customer=alert["customer"],
            property=alert["property"],
            metadata=alert["metadata"],
            delivery=alert["delivery"],
            reviewed_at=alert["reviewed_at"],
            contacted_at=alert["contacted_at"],
            staff_notes=alert["staff_notes"],
        ))
    return alerts


@app.post("/staff/alerts/{alert_id}/status", response_model=AlertResponse)
async def update_alert_status(alert_id: str, update: AlertStatusUpdate):
    alert = alert_store.get(alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    timestamp = datetime.now().isoformat()
    if update.status == "reviewed":
        alert["reviewed_at"] = timestamp
    if update.status == "contacted":
        alert["contacted_at"] = timestamp

    if update.note or update.staff_member:
        alert["staff_notes"].append({
            "timestamp": timestamp,
            "staff_member": update.staff_member,
            "note": update.note
        })

    return AlertResponse(
        id=alert["id"],
        created_at=alert["created_at"],
        alert_type=alert["alert_type"],
        summary=alert["summary"],
        customer=alert["customer"],
        property=alert["property"],
        metadata=alert["metadata"],
        delivery=alert["delivery"],
        reviewed_at=alert["reviewed_at"],
        contacted_at=alert["contacted_at"],
        staff_notes=alert["staff_notes"],
    )


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
