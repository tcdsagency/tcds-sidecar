"""
MMI Cookie Extractor
====================
Extracts session cookies from MMI (Market Data) website.
Required for property history and mortgage data API.
"""

import os
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser


class MMIExtractor:
    """Extract MMI session cookies via browser automation"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
    
    async def extract(self) -> Dict[str, Any]:
        """
        Login to MMI and extract session cookies.
        
        Returns:
            {
                "success": True/False,
                "cookieString": "name=value; ...",
                "sessionCookies": {...},
                "allCookies": {...},
                "error": "..." (if failed)
            }
        """
        email = os.getenv("MMI_EMAIL")
        password = os.getenv("MMI_PASSWORD")
        
        if not email or not password:
            return {"success": False, "error": "MMI_EMAIL and MMI_PASSWORD required"}
        
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            # Navigate to MMI login
            print("[MMI] Navigating to login page...")
            await page.goto("https://new.mmi.run/login", wait_until="networkidle")
            await asyncio.sleep(3)
            
            # Fill login form
            print("[MMI] Filling login form...")
            
            # Find email field
            email_field = None
            for selector in ["input[type='email']", "input[name='email']", "input#email", "input[placeholder*='email' i]"]:
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
            password_field = await page.query_selector("input[type='password']")
            if not password_field:
                return {"success": False, "error": "Could not find password field"}
            
            await password_field.fill(password)
            await asyncio.sleep(1)
            
            # Click submit
            print("[MMI] Submitting login...")
            submit_clicked = False
            
            for selector in ["button[type='submit']", "input[type='submit']", "button.btn-primary"]:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        submit_clicked = True
                        break
                except:
                    continue
            
            if not submit_clicked:
                buttons = await page.query_selector_all("button")
                for btn in buttons:
                    text = (await btn.inner_text()).lower()
                    if any(word in text for word in ["sign in", "log in", "login", "submit"]):
                        await btn.click()
                        submit_clicked = True
                        break
            
            if not submit_clicked:
                return {"success": False, "error": "Could not find login button"}
            
            # Wait for login to complete
            await asyncio.sleep(5)
            
            # Check if still on login page
            if "login" in page.url.lower():
                error_el = await page.query_selector(".error, .alert-danger, [class*='error']")
                if error_el:
                    error_text = await error_el.inner_text()
                    return {"success": False, "error": f"Login failed: {error_text}"}
                
                # Wait a bit more
                await asyncio.sleep(3)
            
            # Extract cookies
            print("[MMI] Extracting cookies...")
            cookies = await context.cookies()
            
            if not cookies:
                return {"success": False, "error": "No cookies found after login"}
            
            # Build cookie string
            cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # Find session-related cookies
            session_cookies = {}
            for cookie in cookies:
                name = cookie['name'].lower()
                if any(term in name for term in ['session', 'auth', 'token', 'jwt', 'sid', 'connect', 'api_key']):
                    session_cookies[cookie['name']] = cookie['value']
            
            # Check localStorage for tokens
            local_storage_token = await page.evaluate("""
                () => {
                    return localStorage.getItem('token') || 
                           localStorage.getItem('access_token') || 
                           localStorage.getItem('jwt') ||
                           localStorage.getItem('auth_token') ||
                           sessionStorage.getItem('token');
                }
            """)
            
            print(f"[MMI] Extracted {len(cookies)} cookies")
            
            return {
                "success": True,
                "cookieString": cookie_string,
                "sessionCookies": session_cookies,
                "allCookies": {c['name']: c['value'] for c in cookies},
                "localStorageToken": local_storage_token,
                "postLoginUrl": page.url,
            }
            
        except Exception as e:
            print(f"[MMI] Error: {e}")
            return {"success": False, "error": str(e)}
        
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.browser = None
            self.playwright = None
