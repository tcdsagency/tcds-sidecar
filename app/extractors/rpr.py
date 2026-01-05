"""
RPR Token Extractor
===================
Extracts JWT token from RPR (Realtors Property Resource) website.
Token is stored in localStorage after login.
"""

import os
import json
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser


class RPRExtractor:
    """Extract RPR JWT token via browser automation"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
    
    async def extract(self) -> Dict[str, Any]:
        """
        Login to RPR and extract JWT token from localStorage.
        
        Returns:
            {
                "token": "eyJ...",
                "expiresIn": 3600,
                "error": "..." (if failed)
            }
        """
        email = os.getenv("RPR_EMAIL")
        password = os.getenv("RPR_PASSWORD")
        
        if not email or not password:
            return {"error": "RPR_EMAIL and RPR_PASSWORD required"}
        
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
            
            # Navigate to RPR
            print("[RPR] Navigating to login page...")
            await page.goto("https://www.narrpr.com/", wait_until="networkidle")
            await asyncio.sleep(3)
            
            # Find and fill login form
            print("[RPR] Looking for login form...")
            
            # Sometimes there's a sign-in link we need to click first
            sign_in_link = await page.query_selector("a[href*='sign-in'], a[href*='login']")
            if sign_in_link:
                await sign_in_link.click()
                await asyncio.sleep(2)
            
            # Fill email
            email_field = None
            for selector in ["input[type='email']", "input[name='email']", "input#email"]:
                try:
                    email_field = await page.wait_for_selector(selector, timeout=5000)
                    if email_field:
                        break
                except:
                    continue
            
            if not email_field:
                return {"error": "Could not find email field"}
            
            await email_field.fill(email)
            
            # Fill password
            password_field = await page.query_selector("input[type='password']")
            if not password_field:
                return {"error": "Could not find password field"}
            
            await password_field.fill(password)
            
            # Submit
            print("[RPR] Submitting login...")
            submit_button = None
            for selector in ["button[type='submit']", "input[type='submit']"]:
                submit_button = await page.query_selector(selector)
                if submit_button:
                    break
            
            if submit_button:
                await submit_button.click()
            else:
                # Try finding button by text
                buttons = await page.query_selector_all("button")
                for btn in buttons:
                    text = (await btn.inner_text()).lower()
                    if "sign" in text or "log" in text:
                        await btn.click()
                        break
            
            # Wait for login to complete
            await asyncio.sleep(5)
            
            # Try to extract token from localStorage
            print("[RPR] Extracting token...")
            token = None
            
            # Direct token keys
            token = await page.evaluate("""
                () => {
                    return localStorage.getItem('token') || 
                           localStorage.getItem('access_token') || 
                           localStorage.getItem('jwt') ||
                           sessionStorage.getItem('token') ||
                           sessionStorage.getItem('access_token');
                }
            """)
            
            # If not found, search all localStorage for JWT-like values
            if not token:
                all_storage = await page.evaluate("""
                    () => {
                        const result = {};
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            result[key] = localStorage.getItem(key);
                        }
                        for (let i = 0; i < sessionStorage.length; i++) {
                            const key = sessionStorage.key(i);
                            result['session_' + key] = sessionStorage.getItem(key);
                        }
                        return result;
                    }
                """)
                
                # Look for JWT-like values (start with eyJ)
                for key, value in all_storage.items():
                    if isinstance(value, str) and value.startswith("eyJ"):
                        token = value
                        print(f"[RPR] Found token in key: {key}")
                        break
            
            # Try navigating to a property page to trigger token creation
            if not token:
                print("[RPR] Token not found, trying property page...")
                await page.goto("https://www.narrpr.com/properties/details/info/17257395", wait_until="networkidle")
                await asyncio.sleep(5)
                
                token = await page.evaluate("""
                    () => {
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            const value = localStorage.getItem(key);
                            if (value && value.startsWith('eyJ')) return value;
                        }
                        return null;
                    }
                """)
            
            # Check cookies as fallback
            if not token:
                cookies = await context.cookies()
                for cookie in cookies:
                    if cookie["value"].startswith("eyJ"):
                        token = cookie["value"]
                        break
                    if "token" in cookie["name"].lower() or "jwt" in cookie["name"].lower():
                        token = cookie["value"]
                        break
            
            if token:
                print(f"[RPR] Token extracted: {token[:50]}...")
                return {
                    "token": token,
                    "expiresIn": 3600
                }
            else:
                return {
                    "error": "Could not extract token",
                    "debug": {
                        "url": page.url,
                        "title": await page.title()
                    }
                }
            
        except Exception as e:
            print(f"[RPR] Error: {e}")
            return {"error": str(e)}
        
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.browser = None
            self.playwright = None
