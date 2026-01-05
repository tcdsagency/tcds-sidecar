"""
Delphi AI Proxy
===============
Browser automation to interact with Delphi chatbot.
The bot runs inside an iframe on TheIntelligentAgent website.
"""

import os
import time
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page


class DelphiProxy:
    """Proxy to interact with Delphi chatbot via browser automation"""
    
    def __init__(self, target_url: str = "https://academy.theintelligentagent.ai/my/"):
        self.target_url = target_url
        self.browser: Optional[Browser] = None
        self.context = None
        self.page: Optional[Page] = None
        self.chat_frame = None
        self.playwright = None
        self.is_initialized = False
        self.authenticated = False
        self.mfa_pending = True
        self.last_activity = None
    
    async def initialize(self, username: str, password: str):
        """Initialize browser and login to the platform"""
        print("[Delphi] Initializing browser...")
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--single-process',
                '--no-zygote',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-sync',
                '--disable-translate',
                '--no-first-run',
                '--disable-default-apps',
                '--mute-audio'
            ]
        )
        
        self.context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        self.page = await self.context.new_page()
        await self.page.set_viewport_size({"width": 1280, "height": 720})
        
        print(f"[Delphi] Navigating to {self.target_url}...")
        await self.page.goto(self.target_url)
        
        try:
            await self.page.wait_for_load_state("networkidle", timeout=20000)
        except:
            await self.page.wait_for_load_state("load", timeout=10000)
        
        # Check if login required
        if "login" in self.page.url.lower():
            print("[Delphi] Login required, authenticating...")
            await asyncio.sleep(1)
            await self._login(username, password)
        
        # Open chat bubble
        print("[Delphi] Opening chat bubble...")
        await self._open_chat_bubble()
        
        self.is_initialized = True
        self.authenticated = True
        self.mfa_pending = False
        self.last_activity = time.time()
        print("[Delphi] Initialization complete!")
    
    async def _login(self, username: str, password: str):
        """Handle login process"""
        try:
            # Wait for login form
            await self.page.wait_for_selector("#username", timeout=10000)
            await self.page.wait_for_selector("#password", timeout=5000)
            
            await self.page.fill("#username", username)
            await asyncio.sleep(0.3)
            await self.page.fill("#password", password)
            await asyncio.sleep(0.3)
            
            await self.page.click("#loginbtn")
            
            await asyncio.sleep(5)
            
            # Check if login succeeded
            if "my" in self.page.url.lower() and "login" not in self.page.url.lower():
                print("[Delphi] Logged in successfully")
                return
            
            try:
                await self.page.wait_for_url("**/my/**", timeout=10000)
                print("[Delphi] Logged in successfully")
                return
            except:
                pass
            
            # Check for errors
            if "login" in self.page.url.lower():
                error_el = await self.page.query_selector(".loginerrors, .alert-danger, .error")
                if error_el:
                    text = await error_el.inner_text()
                    raise Exception(f"Login failed: {text}")
                raise Exception("Login failed: still on login page")
            
            print("[Delphi] Logged in successfully")
            
        except Exception as e:
            print(f"[Delphi] Login failed: {e}")
            raise
    
    async def _open_chat_bubble(self):
        """Open the Delphi chat bubble and get iframe reference"""
        try:
            await self.page.wait_for_selector("#delphi-bubble-trigger", timeout=15000)
            await self.page.click("#delphi-bubble-trigger", force=True)
            await asyncio.sleep(3)
            
            # Check if chat opened
            chat_open = await self.page.query_selector("#delphi-bubble-trigger[data-is-open='true']")
            if not chat_open:
                await self.page.click("#delphi-bubble-trigger", force=True)
                await asyncio.sleep(2)
            
            # Get iframe reference
            iframe_element = await self.page.query_selector("#delphi-frame")
            if iframe_element:
                self.chat_frame = await iframe_element.content_frame()
                if self.chat_frame:
                    await self.chat_frame.wait_for_selector("#message", timeout=10000)
                    print("[Delphi] Chat bubble opened and iframe ready")
                else:
                    print("[Delphi] Warning: Could not access chat iframe content")
            else:
                print("[Delphi] Warning: Chat iframe not found")
                
        except Exception as e:
            print(f"[Delphi] Could not open chat bubble: {e}")
    
    async def send_message(self, message: str, timeout: int = 60) -> str:
        """
        Send message to bot and get response.
        
        Args:
            message: Question to ask
            timeout: Max seconds to wait for response
            
        Returns:
            Bot's response text
        """
        if not self.is_initialized:
            raise RuntimeError("Proxy not initialized. Call initialize() first.")
        
        if not self.chat_frame:
            raise RuntimeError("Chat frame not available. Chat bubble may not have opened.")
        
        print(f"[Delphi] Sending message: {message[:50]}...")
        
        try:
            await self.chat_frame.wait_for_selector("#message", timeout=5000)
            await self.chat_frame.fill("#message", "")
            await self.chat_frame.fill("#message", message)
            await self.chat_frame.press("#message", "Enter")
            
            print("[Delphi] Waiting for response...")
            await asyncio.sleep(3)
            
            start_time = time.time()
            last_response = ""
            stable_count = 0
            
            while time.time() - start_time < timeout:
                response = await self._extract_latest_response()
                
                if response and response != last_response and not response.startswith("Error"):
                    last_response = response
                    stable_count = 0
                else:
                    stable_count += 1
                
                # Response is stable (unchanged for 4 checks)
                if stable_count >= 4 and last_response:
                    break
                
                await asyncio.sleep(1)
            
            self.last_activity = time.time()
            print(f"[Delphi] Received response: {last_response[:100]}...")
            return last_response if last_response else "No response received"
            
        except Exception as e:
            print(f"[Delphi] Error sending message: {e}")
            return f"Error: {str(e)}"
    
    async def _extract_latest_response(self) -> str:
        """Extract the latest bot response from the chat interface"""
        try:
            if not self.chat_frame:
                return "Error: Chat frame not available"
            
            response = await self.chat_frame.evaluate("""
                () => {
                    // Look for prose content divs (the actual message text)
                    const proseMessages = document.querySelectorAll('.prose, [class*="prose"]');
                    const botResponses = [];
                    
                    proseMessages.forEach(el => {
                        let text = el.textContent?.trim() || '';
                        // Clean up the text
                        text = text.replace(/Read Aloud\\s*$/gi, '').trim();
                        text = text.replace(/^Read Aloud\\s*/gi, '').trim();
                        
                        // Skip short messages, user messages, and welcome messages
                        if (text.length > 50 && 
                            !text.startsWith("Hi, I'm your Intelligent Agent") &&
                            !text.includes("Before we continue, what is your email")) {
                            botResponses.push(text);
                        }
                    });
                    
                    // Return the last substantial bot response
                    if (botResponses.length > 0) {
                        return botResponses[botResponses.length - 1];
                    }
                    
                    // If asking for email, return that
                    for (let el of proseMessages) {
                        const text = el.textContent?.trim() || '';
                        if (text.includes("email address")) {
                            return text.replace(/Read Aloud\\s*$/gi, '').trim();
                        }
                    }
                    
                    return "";
                }
            """)
            return response
            
        except Exception as e:
            return f"Error extracting response: {str(e)}"
    
    async def close(self):
        """Clean up browser resources"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
        self.is_initialized = False
        self.authenticated = False
        print("[Delphi] Browser closed")
