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
        Send SMS through AgencyZoom using full browser automation.
        The HTTP API returns fake success, so we must use the actual UI.

        Args:
            phone_number: Recipient phone number (will be normalized)
            message: SMS message body

        Returns:
            {"success": True/False, "error": "..." (if failed)}
        """
        email = os.getenv("AGENCYZOOM_EMAIL") or os.getenv("AGENCYZOOM_API_USERNAME")
        password = os.getenv("AGENCYZOOM_PASSWORD") or os.getenv("AGENCYZOOM_API_PASSWORD")

        if not email or not password:
            return {"success": False, "error": "AGENCYZOOM credentials required"}

        # Normalize phone number
        normalized_phone = ''.join(c for c in phone_number if c.isdigit())
        if len(normalized_phone) == 10:
            normalized_phone = '1' + normalized_phone

        print(f"[AgencyZoom SMS] Starting browser automation for {normalized_phone}")

        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )

            # Set default timeout to 60 seconds for all operations
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            context.set_default_timeout(60000)
            page = await context.new_page()

            # Step 1: Login
            print("[AgencyZoom SMS] Step 1: Logging in...")
            await page.goto("https://app.agencyzoom.com/login", wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # Find and fill email
            email_selectors = ["input[name='LoginForm[username]']", "input[name='email']", "input[type='email']"]
            for sel in email_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(email)
                        print(f"[AgencyZoom SMS] Filled email using {sel}")
                        break
                except:
                    continue

            # Find and fill password
            pw_selectors = ["input[name='LoginForm[password]']", "input[name='password']", "input[type='password']"]
            for sel in pw_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(password)
                        await el.press("Enter")
                        print(f"[AgencyZoom SMS] Submitted login using {sel}")
                        break
                except:
                    continue

            # Wait for login to complete
            await asyncio.sleep(6)
            if "login" in page.url.lower():
                return {"success": False, "error": "Login failed"}
            print("[AgencyZoom SMS] Login successful")

            # Step 2: Navigate to messages
            print("[AgencyZoom SMS] Step 2: Going to messages page...")
            await page.goto("https://app.agencyzoom.com/integration/messages/index", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Step 3: Click Add button
            print("[AgencyZoom SMS] Step 3: Clicking Add...")
            await page.evaluate("""() => {
                const btn = document.querySelector('button.btn-success, a.btn-success')
                    || Array.from(document.querySelectorAll('button, a')).find(e => e.textContent.includes('Add'));
                if (btn) btn.click();
            }""")
            await asyncio.sleep(1.5)

            # Step 4: Click "Send a Text"
            print("[AgencyZoom SMS] Step 4: Clicking Send a Text...")
            await page.evaluate("""() => {
                const link = Array.from(document.querySelectorAll('a')).find(a =>
                    a.textContent.includes('Send a Text') || a.textContent.includes('Send Text') || a.href?.includes('send-text'));
                if (link) link.click();
            }""")
            await asyncio.sleep(2)

            # Step 5: Enter phone number
            print(f"[AgencyZoom SMS] Step 5: Entering phone {normalized_phone}...")
            # Try tagify input first
            tagify = await page.query_selector(".tagify__input")
            if tagify:
                await tagify.click()
                await tagify.type(normalized_phone, delay=50)
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")
            else:
                # Try regular input
                await page.evaluate(f"""() => {{
                    const inp = document.querySelector('input[name="recipients"]') || document.querySelector('.tagify input');
                    if (inp) {{ inp.value = '{normalized_phone}'; inp.dispatchEvent(new Event('input', {{bubbles:true}})); }}
                }}""")
            await asyncio.sleep(1)

            # Step 6: Enter message
            print("[AgencyZoom SMS] Step 6: Entering message...")
            safe_msg = message.replace("'", "\\'").replace("\n", " ")
            await page.evaluate(f"""() => {{
                const ta = document.getElementById('textMessage') || document.querySelector('textarea[name="message"]') || document.querySelector('textarea');
                if (ta) {{
                    ta.value = '{safe_msg}';
                    ta.dispatchEvent(new Event('input', {{bubbles:true}}));
                    ta.dispatchEvent(new Event('change', {{bubbles:true}}));
                }}
            }}""")
            await asyncio.sleep(1)

            # Step 7: Click Send
            print("[AgencyZoom SMS] Step 7: Clicking Send...")
            await page.evaluate("""() => {
                const btn = document.getElementById('send-text-btn')
                    || document.querySelector('button[type="submit"]')
                    || Array.from(document.querySelectorAll('button')).find(b => b.textContent.toLowerCase().includes('send'));
                if (btn) btn.click();
            }""")
            await asyncio.sleep(3)

            # Check for errors
            error_el = await page.query_selector(".alert-danger:visible, .toast-error:visible")
            if error_el:
                err_text = await error_el.inner_text()
                return {"success": False, "error": f"AgencyZoom error: {err_text}"}

            print("[AgencyZoom SMS] SMS sent successfully!")
            return {"success": True}

        except Exception as e:
            print(f"[AgencyZoom SMS] Error: {e}")
            return {"success": False, "error": str(e)}

        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.browser = None
            self.playwright = None
