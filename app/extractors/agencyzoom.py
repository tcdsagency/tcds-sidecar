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

    async def _get_cookies(self) -> Optional[List[Dict[str, Any]]]:
        """Get cookies from cache or extract fresh ones."""
        if self._cached_cookies:
            print("[AgencyZoom SMS] Using cached cookies")
            return self._cached_cookies

        print("[AgencyZoom SMS] No cached cookies, extracting fresh session...")
        result = await self.extract()
        if result.get("success"):
            return self._cached_cookies
        return None

    async def send_sms(self, phone_number: str, message: str) -> Dict[str, Any]:
        """
        Send SMS through AgencyZoom using HTTP with session cookies.

        Args:
            phone_number: Recipient phone number (will be normalized)
            message: SMS message body

        Returns:
            {"success": True/False, "error": "..." (if failed)}
        """
        # Normalize phone number - AgencyZoom expects format like "12056173229"
        normalized_phone = ''.join(c for c in phone_number if c.isdigit())
        if len(normalized_phone) == 10:
            normalized_phone = '1' + normalized_phone

        print(f"[AgencyZoom SMS] Preparing to send to {normalized_phone}")

        # Get cookies (cached or fresh)
        cookies = await self._get_cookies()
        if not cookies:
            return {"success": False, "error": "Could not get session cookies"}

        # Build cookie jar for aiohttp
        jar = aiohttp.CookieJar()
        for c in cookies:
            jar.update_cookies({c["name"]: c["value"]})

        # Build cookie header string
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        try:
            async with aiohttp.ClientSession() as session:
                # Try the send-text endpoint with session cookies
                # The endpoint is at /integration/sms/send-text
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cookie": cookie_str,
                    "Origin": "https://app.agencyzoom.com",
                    "Referer": "https://app.agencyzoom.com/integration/messages/index",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                }

                # Add CSRF token if we have it
                if self._cached_csrf:
                    headers["X-CSRF-Token"] = self._cached_csrf

                # Try the API endpoint format AgencyZoom expects
                payload = {
                    "PhoneNumber": normalized_phone,
                    "Message": message,
                    "UserId": "",  # Empty for system
                    "FromName": "TCDS Agency"
                }

                print(f"[AgencyZoom SMS] Sending HTTP request...")
                async with session.post(
                    "https://app.agencyzoom.com/integration/sms/send-text",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    text = await resp.text()
                    print(f"[AgencyZoom SMS] Response: {resp.status} - {text[:200]}")

                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            if data.get("result") or data.get("success"):
                                print("[AgencyZoom SMS] SMS sent successfully!")
                                return {"success": True}
                            else:
                                return {"success": False, "error": data.get("message", "Unknown error")}
                        except:
                            # If response isn't JSON, check if it looks like success
                            if "success" in text.lower() or "sent" in text.lower():
                                return {"success": True}
                            return {"success": False, "error": f"Unexpected response: {text[:100]}"}
                    elif resp.status == 401 or resp.status == 403:
                        # Session expired, clear cache and retry once
                        print("[AgencyZoom SMS] Session expired, refreshing...")
                        self._cached_cookies = None
                        self._cached_csrf = None
                        cookies = await self._get_cookies()
                        if not cookies:
                            return {"success": False, "error": "Could not refresh session"}
                        # Retry with new cookies
                        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                        headers["Cookie"] = cookie_str
                        if self._cached_csrf:
                            headers["X-CSRF-Token"] = self._cached_csrf

                        async with session.post(
                            "https://app.agencyzoom.com/integration/sms/send-text",
                            headers=headers,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as retry_resp:
                            retry_text = await retry_resp.text()
                            if retry_resp.status == 200:
                                return {"success": True}
                            return {"success": False, "error": f"Retry failed: {retry_text[:100]}"}
                    else:
                        return {"success": False, "error": f"HTTP {resp.status}: {text[:100]}"}

        except asyncio.TimeoutError:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            print(f"[AgencyZoom SMS] Error: {e}")
            return {"success": False, "error": str(e)}
