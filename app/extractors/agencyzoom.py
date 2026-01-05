"""
AgencyZoom Session Extractor
============================
Extracts session cookies and CSRF token for SMS endpoint.
The /integration/sms/send-text endpoint requires session cookies, not JWT.
"""

import os
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, Page


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
