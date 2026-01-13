#!/usr/bin/env python3
"""
AgencyZoom SMS Service for VM
=============================
Runs on GCP VM with full browser automation for reliable SMS sending.
"""

import os
import asyncio
from typing import Optional
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright

app = FastAPI(title="AgencyZoom SMS Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SMSRequest(BaseModel):
    phone_number: str
    message: str

class SMSResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    step: Optional[str] = None

# Credentials from environment
EMAIL = os.getenv("AGENCYZOOM_EMAIL") or os.getenv("AGENCYZOOM_API_USERNAME", "service@tcdsagency.com")
PASSWORD = os.getenv("AGENCYZOOM_PASSWORD") or os.getenv("AGENCYZOOM_API_PASSWORD", "Welcome2023!")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "agencyzoom-sms", "timestamp": datetime.now().isoformat()}

@app.post("/send", response_model=SMSResponse)
async def send_sms(request: SMSRequest):
    """Send SMS via AgencyZoom browser automation."""

    # Normalize phone
    phone = ''.join(c for c in request.phone_number if c.isdigit())
    if len(phone) == 10:
        phone = '1' + phone

    print(f"[SMS] Starting browser automation for {phone}")

    playwright = None
    browser = None

    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )

        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        context.set_default_timeout(60000)
        page = await context.new_page()

        # Step 1: Login
        print("[SMS] Step 1: Login")
        await page.goto("https://app.agencyzoom.com/login", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Fill email
        email_field = await page.query_selector("input[name='LoginForm[username]']")
        if not email_field:
            email_field = await page.query_selector("input[type='email']")
        if email_field:
            await email_field.fill(EMAIL)
        else:
            return SMSResponse(success=False, error="Email field not found", step="login")

        # Fill password and submit
        pw_field = await page.query_selector("input[name='LoginForm[password]']")
        if not pw_field:
            pw_field = await page.query_selector("input[type='password']")
        if pw_field:
            await pw_field.fill(PASSWORD)
            await pw_field.press("Enter")
        else:
            return SMSResponse(success=False, error="Password field not found", step="login")

        await asyncio.sleep(6)

        if "login" in page.url.lower():
            # Take screenshot for debugging
            await page.screenshot(path="/tmp/login_failed.png")
            return SMSResponse(success=False, error="Login failed - still on login page", step="login")

        print("[SMS] Login successful")

        # Step 2: Go to messages
        print("[SMS] Step 2: Navigate to messages")
        await page.goto("https://app.agencyzoom.com/integration/messages/index", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Step 3: Click Add
        print("[SMS] Step 3: Click Add button")
        add_clicked = await page.evaluate("""() => {
            const btn = document.querySelector('button.btn-success')
                || Array.from(document.querySelectorAll('button, a')).find(e =>
                    e.textContent.trim() === 'Add' || e.textContent.includes('Add'));
            if (btn) { btn.click(); return true; }
            return false;
        }""")

        if not add_clicked:
            await page.screenshot(path="/tmp/add_button_failed.png")
            return SMSResponse(success=False, error="Add button not found", step="add_button")

        await asyncio.sleep(1.5)

        # Step 4: Click "Send a Text"
        print("[SMS] Step 4: Click Send a Text")
        send_text_clicked = await page.evaluate("""() => {
            const link = Array.from(document.querySelectorAll('a')).find(a =>
                a.textContent.includes('Send a Text') || a.textContent.includes('Send Text'));
            if (link) { link.click(); return true; }
            return false;
        }""")

        if not send_text_clicked:
            await page.screenshot(path="/tmp/send_text_failed.png")
            return SMSResponse(success=False, error="Send a Text link not found", step="send_text")

        await asyncio.sleep(2)

        # Step 5: Enter phone number using JS to avoid viewport issues
        print(f"[SMS] Step 5: Enter phone {phone}")
        phone_entered = await page.evaluate(f"""() => {{
            const tagify = document.querySelector('.tagify__input');
            if (tagify) {{
                tagify.scrollIntoView();
                tagify.click();
                tagify.focus();
                // Simulate typing by creating and dispatching input event
                tagify.textContent = '{phone}';
                tagify.dispatchEvent(new InputEvent('input', {{bubbles: true, data: '{phone}'}}));
                // Press Enter
                tagify.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}}));
                return true;
            }}
            return false;
        }}""")

        if not phone_entered:
            # Fallback to regular input
            await page.evaluate(f"""() => {{
                const inp = document.querySelector('input[name="recipients"]');
                if (inp) {{ inp.value = '{phone}'; inp.dispatchEvent(new Event('input', {{bubbles:true}})); }}
            }}""")

        await asyncio.sleep(1.5)

        # Step 6: Enter message
        print("[SMS] Step 6: Enter message")
        safe_msg = request.message.replace("'", "\\'").replace("\n", " ").replace("\r", "")
        await page.evaluate(f"""() => {{
            const ta = document.getElementById('textMessage')
                || document.querySelector('textarea[name="message"]')
                || document.querySelector('textarea');
            if (ta) {{
                ta.value = '{safe_msg}';
                ta.dispatchEvent(new Event('input', {{bubbles:true}}));
                ta.dispatchEvent(new Event('change', {{bubbles:true}}));
            }}
        }}""")
        await asyncio.sleep(1)

        # Step 7: Click Send
        print("[SMS] Step 7: Click Send")
        await page.screenshot(path="/tmp/before_send.png")

        send_clicked = await page.evaluate("""() => {
            const btn = document.getElementById('send-text-btn')
                || document.querySelector('button[type="submit"]')
                || Array.from(document.querySelectorAll('button')).find(b =>
                    b.textContent.toLowerCase().includes('send') && !b.textContent.toLowerCase().includes('text'));
            if (btn) { btn.click(); return true; }
            return false;
        }""")

        if not send_clicked:
            await page.screenshot(path="/tmp/send_button_failed.png")
            return SMSResponse(success=False, error="Send button not found", step="send")

        await asyncio.sleep(4)

        # Check for error
        await page.screenshot(path="/tmp/after_send.png")
        error_el = await page.query_selector(".alert-danger")
        if error_el:
            is_visible = await error_el.is_visible()
            if is_visible:
                error_text = await error_el.inner_text()
                return SMSResponse(success=False, error=f"AgencyZoom error: {error_text}", step="send")

        print("[SMS] SMS sent successfully!")
        return SMSResponse(success=True)

    except Exception as e:
        print(f"[SMS] Error: {e}")
        return SMSResponse(success=False, error=str(e))

    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8901))
    uvicorn.run(app, host="0.0.0.0", port=port)
