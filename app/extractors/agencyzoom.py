"""
AgencyZoom Session Extractor
============================
Extracts session cookies and CSRF token for SMS endpoint.
Also provides SMS sending via HTTP with session cookies.
The /integration/sms/send-text endpoint requires session cookies, not JWT.
"""

import os
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from playwright.async_api import async_playwright, Browser, Page, BrowserContext


class AgencyZoomExtractor:
    """Extract AgencyZoom session cookies via browser automation"""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
        self._cached_cookies: Optional[List[Dict[str, Any]]] = None
        self._cached_csrf: Optional[str] = None
    
    async def extract(self) -> Dict[str, Any]:
        """
        Login to AgencyZoom and extract session cookies + CSRF token.
        
        Returns:
            {
                "success": True/False,
                "cookies": [...],
                "csrfToken": "...",
                "error": "..." (if failed)
            }
        """
        email = os.getenv("AGENCYZOOM_EMAIL") or os.getenv("AGENCYZOOM_API_USERNAME")
        password = os.getenv("AGENCYZOOM_PASSWORD") or os.getenv("AGENCYZOOM_API_PASSWORD")
        
        if not email or not password:
            return {
                "success": False,
                "error": "AGENCYZOOM_EMAIL and AGENCYZOOM_PASSWORD required"
            }
        
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ]
            )
            
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            # Navigate to login
            print("[AgencyZoom] Navigating to login page...")
            await page.goto("https://app.agencyzoom.com/login", wait_until="networkidle")
            await asyncio.sleep(2)
            
            # Fill login form
            print("[AgencyZoom] Filling login form...")
            
            # Try multiple selectors for email field
            email_field = None
            for selector in ["input[name='email']", "input[type='email']", "#email"]:
                try:
                    email_field = await page.wait_for_selector(selector, timeout=5000)
                    if email_field:
                        break
                except:
                    continue
            
            if not email_field:
                return {"success": False, "error": "Could not find email field"}
            
            await email_field.fill(email)
            
            # Find password field
            password_field = None
            for selector in ["input[name='password']", "input[type='password']", "#password"]:
                try:
                    password_field = await page.query_selector(selector)
                    if password_field:
                        break
                except:
                    continue
            
            if not password_field:
                return {"success": False, "error": "Could not find password field"}
            
            await password_field.fill(password)
            
            # Click login button
            login_button = None
            for selector in ["button[type='submit']", "input[type='submit']", ".btn-primary"]:
                try:
                    login_button = await page.query_selector(selector)
                    if login_button:
                        break
                except:
                    continue
            
            if login_button:
                await login_button.click()
            else:
                # Try pressing Enter
                await password_field.press("Enter")
            
            # Wait for redirect
            print("[AgencyZoom] Waiting for login...")
            await asyncio.sleep(5)
            
            # Check if login succeeded
            if "login" in page.url.lower():
                # Check for error messages
                error_el = await page.query_selector(".error-message, .alert-danger")
                if error_el:
                    error_text = await error_el.inner_text()
                    return {"success": False, "error": f"Login failed: {error_text}"}
                return {"success": False, "error": "Login failed: still on login page"}
            
            # Navigate to SMS page to get CSRF token
            print("[AgencyZoom] Getting CSRF token...")
            await page.goto("https://app.agencyzoom.com/integration/messages/index", wait_until="networkidle")
            await asyncio.sleep(2)
            
            # Extract CSRF token
            csrf_token = None
            try:
                csrf_meta = await page.query_selector("meta[name='csrf-token']")
                if csrf_meta:
                    csrf_token = await csrf_meta.get_attribute("content")
            except:
                pass
            
            # Get cookies
            cookies = await context.cookies()
            cookie_list = [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                for c in cookies
            ]
            
            print(f"[AgencyZoom] Extracted {len(cookie_list)} cookies")

            # Cache cookies for SMS sending
            self._cached_cookies = cookie_list
            self._cached_csrf = csrf_token

            result = {
                "success": True,
                "cookies": cookie_list,
            }
            if csrf_token:
                result["csrfToken"] = csrf_token

            return result
            
        except Exception as e:
            print(f"[AgencyZoom] Error: {e}")
            return {"success": False, "error": str(e)}
        
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.browser = None
            self.playwright = None

    async def send_sms(self, phone_number: str, message: str) -> Dict[str, Any]:
        """
        Send SMS through AgencyZoom using HTTP API with session cookies.

        Args:
            phone_number: Recipient phone number (will be normalized)
            message: SMS message body

        Returns:
            {"success": True/False, "error": "..." (if failed)}
        """
        import base64
        import json as json_module

        # Normalize phone number
        normalized_phone = ''.join(c for c in phone_number if c.isdigit())
        if len(normalized_phone) == 10:
            normalized_phone = '1' + normalized_phone

        print(f"[AgencyZoom SMS] Preparing to send to {normalized_phone}")

        # Get fresh session if needed
        if not self._cached_cookies:
            print("[AgencyZoom SMS] No cached cookies, extracting session...")
            result = await self.extract()
            if not result.get("success"):
                return {"success": False, "error": "Could not get session"}

        # Extract user ID from JWT cookie
        user_id = ""
        jwt_token = ""
        for c in self._cached_cookies:
            if c["name"] == "jwt":
                jwt_token = c["value"]
                try:
                    # JWT format: header.payload.signature
                    payload = jwt_token.split(".")[1]
                    # Add padding if needed
                    payload += "=" * (4 - len(payload) % 4)
                    decoded = base64.b64decode(payload)
                    jwt_data = json_module.loads(decoded)
                    # User ID is in the "u" field (base64 encoded)
                    u_encoded = jwt_data.get("jti", {}).get("u", "")
                    if u_encoded:
                        user_id = base64.b64decode(u_encoded + "==").decode()
                    print(f"[AgencyZoom SMS] Extracted user ID: {user_id}")
                except Exception as e:
                    print(f"[AgencyZoom SMS] Could not extract user ID: {e}")
                break

        # Build cookie header string
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in self._cached_cookies])

        # Use CSRF token from meta tag (not cookie - cookie is URL-encoded data)
        csrf_token = self._cached_csrf or ""

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Cookie": cookie_str,
                    "Origin": "https://app.agencyzoom.com",
                    "Referer": "https://app.agencyzoom.com/integration/messages/index",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                }

                # Add CSRF token
                if csrf_token:
                    headers["X-CSRF-Token"] = csrf_token

                # Payload per the diagram
                payload = {
                    "PhoneNumber": normalized_phone,
                    "UserId": user_id,
                    "Message": message,
                    "FromName": "TCDS Agency"
                }

                print(f"[AgencyZoom SMS] Sending HTTP request with UserId={user_id}...")
                print(f"[AgencyZoom SMS] CSRF Token: {csrf_token[:50] if csrf_token else 'None'}...")

                async with session.post(
                    "https://app.agencyzoom.com/integration/sms/send-text",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    text = await resp.text()
                    print(f"[AgencyZoom SMS] Response {resp.status}: {text}")

                    if resp.status == 200:
                        try:
                            data = json_module.loads(text)
                            # Check if there's an actual SMS ID returned
                            if data.get("id"):
                                print(f"[AgencyZoom SMS] SMS sent with ID: {data.get('id')}")
                                return {"success": True, "sms_id": data.get("id")}
                            elif data.get("result") == True:
                                # This is the "fake success" - returns true but no ID
                                print("[AgencyZoom SMS] Got result=true but no ID - may be fake success")
                                return {"success": True, "warning": "No SMS ID returned"}
                            else:
                                return {"success": False, "error": data.get("message", text)}
                        except:
                            return {"success": False, "error": f"Invalid response: {text[:100]}"}
                    else:
                        return {"success": False, "error": f"HTTP {resp.status}: {text[:100]}"}

        except asyncio.TimeoutError:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            print(f"[AgencyZoom SMS] Error: {e}")
            return {"success": False, "error": str(e)}
