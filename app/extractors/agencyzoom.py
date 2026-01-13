"""
AgencyZoom Session Extractor
============================
Extracts session cookies and CSRF token for SMS endpoint.
Also provides SMS sending via browser automation.
The /integration/sms/send-text endpoint requires session cookies, not JWT.
"""

import os
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext


class AgencyZoomExtractor:
    """Extract AgencyZoom session cookies via browser automation"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
    
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
        Send SMS through AgencyZoom's web interface using browser automation.

        Args:
            phone_number: Recipient phone number (will be normalized)
            message: SMS message body

        Returns:
            {"success": True/False, "error": "..." (if failed)}
        """
        email = os.getenv("AGENCYZOOM_EMAIL") or os.getenv("AGENCYZOOM_API_USERNAME")
        password = os.getenv("AGENCYZOOM_PASSWORD") or os.getenv("AGENCYZOOM_API_PASSWORD")

        if not email or not password:
            return {
                "success": False,
                "error": "AGENCYZOOM_EMAIL and AGENCYZOOM_PASSWORD required"
            }

        # Normalize phone number
        normalized_phone = ''.join(c for c in phone_number if c.isdigit())
        if len(normalized_phone) == 10:
            normalized_phone = '1' + normalized_phone
        elif normalized_phone.startswith('1') and len(normalized_phone) == 11:
            pass  # Already has country code

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

            # Login first
            print("[AgencyZoom SMS] Navigating to login page...")
            await page.goto("https://app.agencyzoom.com/login", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)

            # Fill login form - try multiple selectors like extract() does
            print("[AgencyZoom SMS] Looking for email field...")
            email_field = None
            for selector in ["input[name='LoginForm[username]']", "input[name='email']", "input[type='email']", "#email"]:
                try:
                    email_field = await page.wait_for_selector(selector, timeout=5000)
                    if email_field:
                        print(f"[AgencyZoom SMS] Found email field with: {selector}")
                        break
                except:
                    continue

            if not email_field:
                return {"success": False, "error": "Could not find email field"}
            await email_field.fill(email)

            # Find password field
            password_field = None
            for selector in ["input[name='LoginForm[password]']", "input[name='password']", "input[type='password']", "#password"]:
                try:
                    password_field = await page.query_selector(selector)
                    if password_field:
                        break
                except:
                    continue

            if not password_field:
                return {"success": False, "error": "Could not find password field"}
            await password_field.fill(password)

            # Submit login
            print("[AgencyZoom SMS] Submitting login...")
            await password_field.press("Enter")
            await asyncio.sleep(8)

            # Check login success
            if "login" in page.url.lower():
                return {"success": False, "error": "Login failed"}

            print("[AgencyZoom SMS] Login successful, navigating to messages...")

            # Navigate to Messages page
            await page.goto("https://app.agencyzoom.com/integration/messages/index", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            # Step 1: Click "Add" button
            print("[AgencyZoom SMS] Clicking Add button...")
            add_clicked = await page.evaluate("""
                () => {
                    const addBtn = Array.from(document.querySelectorAll('button, a'))
                        .find(el => el.textContent.trim() === 'Add' || el.textContent.includes('Add'));
                    if (addBtn) { addBtn.click(); return true; }
                    return false;
                }
            """)
            if not add_clicked:
                return {"success": False, "error": "Could not find Add button"}
            await asyncio.sleep(1)

            # Step 2: Click "Send a Text" link
            print("[AgencyZoom SMS] Clicking 'Send a Text'...")
            send_text_clicked = await page.evaluate("""
                () => {
                    const link = Array.from(document.querySelectorAll('a'))
                        .find(a => a.textContent.includes('Send a Text') || a.textContent.includes('Send Text'));
                    if (link) { link.click(); return true; }
                    return false;
                }
            """)
            if not send_text_clicked:
                return {"success": False, "error": "Could not find 'Send a Text' option"}
            await asyncio.sleep(2)

            # Step 3: Enter phone number in tagify input
            print(f"[AgencyZoom SMS] Entering phone number: {normalized_phone}")

            # Try to find and interact with tagify input
            tagify_input = await page.query_selector(".tagify__input")
            if tagify_input:
                await tagify_input.click()
                await asyncio.sleep(0.5)
                await tagify_input.type(normalized_phone)
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
                await asyncio.sleep(1)
            else:
                # Fallback: try direct input
                await page.evaluate(f"""
                    () => {{
                        const input = document.querySelector('input[name="recipients"]')
                            || document.querySelector('.tagify input');
                        if (input) {{
                            input.value = '{normalized_phone}';
                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        }}
                    }}
                """)

            # Step 4: Enter message
            print("[AgencyZoom SMS] Entering message...")
            escaped_message = message.replace("'", "\\'").replace("\n", "\\n")
            await page.evaluate(f"""
                () => {{
                    const textarea = document.getElementById('textMessage')
                        || document.querySelector('textarea[name="message"]')
                        || document.querySelector('textarea');
                    if (textarea) {{
                        textarea.value = '{escaped_message}';
                        textarea.focus();
                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}
            """)
            await asyncio.sleep(1)

            # Step 5: Click Send button
            print("[AgencyZoom SMS] Clicking Send...")
            send_clicked = await page.evaluate("""
                () => {
                    const sendBtn = document.getElementById('send-text-btn')
                        || document.querySelector('button[type="submit"]')
                        || Array.from(document.querySelectorAll('button'))
                            .find(btn => btn.textContent.toLowerCase().includes('send'));
                    if (sendBtn) { sendBtn.click(); return true; }
                    return false;
                }
            """)

            if not send_clicked:
                return {"success": False, "error": "Could not find Send button"}

            # Wait for send to complete
            await asyncio.sleep(3)

            # Check for success/error indicators
            error_el = await page.query_selector(".alert-danger, .toast-error, .error-message")
            if error_el:
                is_visible = await error_el.is_visible()
                if is_visible:
                    error_text = await error_el.inner_text()
                    return {"success": False, "error": f"Send failed: {error_text}"}

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
