"""
WhatsApp Service
Handles WhatsApp message retrieval and operations using Playwright
"""

import logging
import os
import asyncio
import base64
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
import json
import time

from models.schemas import WhatsAppMessage, WhatsAppContact

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class WhatsAppService:
    """Service for handling WhatsApp operations using Playwright"""
    
    def __init__(self):
        """Initialize WhatsApp service"""
        load_dotenv(override=True)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_connected = False
        self.qr_code = None
        self.qr_code_base64 = None
        self.qr_code_timestamp = None  # Track when QR code was generated
        self.session_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'whatsapp_session')
        os.makedirs(self.session_path, exist_ok=True)
        
        # Check if session exists
        self.has_session = self._check_session_exists()
        
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available. Install with: pip install playwright && playwright install chromium")
        else:
            logger.info("WhatsApp service initialized")
    
    def _check_session_exists(self) -> bool:
        """Check if WhatsApp session files exist and are valid"""
        # Check for Playwright browser context storage
        storage_file = os.path.join(self.session_path, 'storage_state.json')
        if os.path.exists(storage_file):
            try:
                file_size = os.path.getsize(storage_file)
                if file_size == 0:
                    logger.warning("Session file exists but is empty")
                    return False
                
                with open(storage_file, 'r') as f:
                    storage = json.load(f)
                    # Check if we have cookies for WhatsApp
                    cookies = storage.get('cookies', [])
                    whatsapp_cookies = [c for c in cookies if 'whatsapp.com' in c.get('domain', '')]
                    
                    # Check for important WhatsApp cookies
                    important_cookies = ['wa', 'wac', 'c_user', 'xs']
                    has_important_cookies = any(
                        any(important in c.get('name', '').lower() for important in important_cookies)
                        for c in whatsapp_cookies
                    )
                    
                    if whatsapp_cookies and (has_important_cookies or len(whatsapp_cookies) >= 3):
                        logger.info(f"✓ Found valid session file with {len(whatsapp_cookies)} WhatsApp cookies (file size: {file_size} bytes)")
                        return True
                    elif whatsapp_cookies:
                        logger.warning(f"Session file has {len(whatsapp_cookies)} cookies but may be incomplete")
                        return True  # Still try to use it
                    elif storage.get('origins'):
                        # Check if origins have localStorage data (indicates active session)
                        origins = storage.get('origins', [])
                        for origin in origins:
                            if origin.get('origin') == 'https://web.whatsapp.com':
                                localStorage = origin.get('localStorage', [])
                                if localStorage:
                                    # Check for important keys like WANoiseInfo, Session, etc.
                                    important_keys = ['WANoiseInfo', 'Session', 'WALid', 'last-wid-md']
                                    has_important_keys = any(
                                        any(key in item.get('name', '') for key in important_keys)
                                        for item in localStorage
                                    )
                                    if has_important_keys:
                                        logger.info(f"Session file has origins data with {len(localStorage)} localStorage items")
                                        return True
                        logger.info("Session file has origins data")
                        return True
                    else:
                        logger.warning("Session file exists but has no WhatsApp cookies")
                        return False
            except json.JSONDecodeError as e:
                logger.warning(f"Session file is corrupted (invalid JSON): {e}")
                return False
            except Exception as e:
                logger.warning(f"Error reading session file: {e}")
                return False
        
        # Check for cookies file as backup
        cookies_file = os.path.join(self.session_path, 'cookies.json')
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file, 'r') as f:
                    cookies = json.load(f)
                    whatsapp_cookies = [c for c in cookies if 'whatsapp.com' in c.get('domain', '')]
                    if whatsapp_cookies and len(whatsapp_cookies) >= 3:
                        logger.info(f"Found existing cookies file with {len(whatsapp_cookies)} WhatsApp cookies")
                        return True
            except:
                pass
        
        logger.info("No valid session file found")
        return False
    
    async def initialize(self):
        """Initialize WhatsApp client connection"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            return
        
        try:
            # Start Playwright
            self.playwright = await async_playwright().start()
            
            # Launch browser with persistent context for session storage
            storage_file = os.path.join(self.session_path, 'storage_state.json')
            context_options = {
                'viewport': {'width': 1280, 'height': 720},
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'locale': 'en-US',
                'timezone_id': 'America/New_York',
                'permissions': ['geolocation'],
                'extra_http_headers': {
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            }
            
            # Load existing session if available
            if os.path.exists(storage_file):
                try:
                    # Validate session file before loading
                    file_size = os.path.getsize(storage_file)
                    if file_size > 0:
                        with open(storage_file, 'r') as f:
                            storage = json.load(f)
                            cookies = storage.get('cookies', [])
                            origins = storage.get('origins', [])
                            whatsapp_cookies = [c for c in cookies if 'whatsapp.com' in c.get('domain', '')]
                            
                            if whatsapp_cookies or origins:
                                context_options['storage_state'] = storage_file
                                logger.info(f"✓ Loading WhatsApp session from {storage_file} ({len(whatsapp_cookies)} cookies, {len(origins)} origins)")
                                self.has_session = True
                            else:
                                logger.warning(f"Session file exists but has no valid data (cookies: {len(cookies)}, origins: {len(origins)})")
                                self.has_session = False
                    else:
                        logger.warning("Session file exists but is empty")
                        self.has_session = False
                except json.JSONDecodeError as e:
                    logger.warning(f"Session file is corrupted (invalid JSON): {e}")
                    self.has_session = False
                except Exception as e:
                    logger.warning(f"Could not load session file: {e}")
                    self.has_session = False
            else:
                logger.info("No session file found - will require QR code authentication")
                self.has_session = False
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process'
                ]
            )
            
            self.context = await self.browser.new_context(**context_options)
            
            # Remove webdriver property to avoid detection
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            self.page = await self.context.new_page()
            
            # Navigate to WhatsApp Web
            logger.info("Navigating to WhatsApp Web...")
            await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=60000)
            
            # Wait for page to fully load
            logger.info("Waiting for page to load...")
            await asyncio.sleep(3)
            
            # Wait for either authentication or QR code to appear
            try:
                await self.page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass
            
            # Check if already logged in (wait longer if we have a session)
            is_authenticated = False
            if self.has_session:
                # If we have a session, wait longer for authentication check
                logger.info("Session file exists, checking authentication (waiting up to 20 seconds)...")
                # Wait a bit longer for WhatsApp Web to restore session
                await asyncio.sleep(5)
                
                for i in range(20):  # Check up to 20 times over 20 seconds
                    is_authenticated = await self._check_authentication_status()
                    if is_authenticated:
                        logger.info(f"✓ Authentication confirmed with existing session (checked {i+1} times)")
                        break
                    if i % 5 == 0 and i > 0:
                        logger.info(f"Still checking authentication... ({i+1}/20)")
                    await asyncio.sleep(1)
                
                if not is_authenticated:
                    logger.warning("Session file exists but authentication check failed. Session may be expired.")
                    # Check if QR code is actually visible (session might be invalid)
                    try:
                        qr_visible = await self.page.evaluate('document.querySelector("div[data-ref]") !== null')
                        if qr_visible:
                            logger.warning("QR code is visible - session is invalid or expired")
                            self.has_session = False  # Mark session as invalid
                        else:
                            # No QR code but not authenticated - might still be loading
                            logger.info("No QR code visible, but not fully authenticated yet. Waiting a bit more...")
                            await asyncio.sleep(5)
                            is_authenticated = await self._check_authentication_status()
                    except:
                        pass
            else:
                # No session, quick check
                logger.info("No session file found, checking for existing authentication...")
                try:
                    is_authenticated = await asyncio.wait_for(
                        self._check_authentication_status(),
                        timeout=3.0
                    )
                except asyncio.TimeoutError:
                    pass
            
            if not is_authenticated:
                # Only show QR code if we don't have a valid session
                if not self.has_session:
                    logger.info("No session found, showing QR code for authentication")
                    # Check for QR code
                    await self._update_qr_code()
                    
                    # Start monitoring for authentication after QR code is shown
                    # This will detect when user scans QR code and save session
                    asyncio.create_task(self._monitor_authentication())
                else:
                    # We have a session but authentication check failed
                    # Check if QR code is actually visible (session might be invalid)
                    try:
                        qr_visible = await self.page.evaluate('document.querySelector("div[data-ref]") !== null')
                        if qr_visible:
                            logger.warning("Session exists but QR code is visible - session may be expired. Will show QR code.")
                            # Session is invalid, show QR code
                            await self._update_qr_code()
                            asyncio.create_task(self._monitor_authentication())
                        else:
                            # No QR code visible - session might still be loading
                            logger.info("Session exists but not authenticated yet. No QR code visible - session may still be loading.")
                            logger.info("QR code will NOT be shown automatically. Click 'Refresh' to check status.")
                            # Don't show QR code - let status check handle it
                    except Exception as e:
                        logger.warning(f"Could not check QR visibility: {e}. Not showing QR code automatically.")
            else:
                logger.info("✓ Successfully authenticated with existing session - no QR code needed")
                # Ensure QR code is cleared
                self.qr_code = None
                self.qr_code_base64 = None
                self.qr_code_timestamp = None
            
            logger.info("WhatsApp service initialized")
                
        except Exception as e:
            logger.error(f"Error initializing WhatsApp service: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _check_authentication_status(self):
        """Check if user is authenticated"""
        try:
            if not self.page:
                return False
            
            # Wait a moment for page to settle
            await asyncio.sleep(0.5)
            
            # Check current URL
            current_url = self.page.url
            logger.debug(f"Checking authentication - Current URL: {current_url}")
            
            # Use JavaScript to check for authentication indicators (more reliable)
            try:
                # Check if QR code container exists
                qr_exists = await self.page.evaluate("""
                    () => {
                        const qrSelectors = [
                            'div[data-ref] canvas',
                            'div[data-ref] img',
                            'canvas[aria-label*="QR"]',
                            'div._2EZ_m',
                            'div[data-ref]'
                        ];
                        for (let selector of qrSelectors) {
                            const elem = document.querySelector(selector);
                            if (elem && elem.offsetParent !== null) { // Check if visible
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                # Check for authenticated state indicators with more comprehensive checks
                auth_indicators = await self.page.evaluate("""
                    () => {
                        const results = {};
                        
                        // Check for chat list
                        results.chatlist = !!document.querySelector('div[data-testid="chatlist"]');
                        
                        // Check for sidebar
                        results.sidebar = !!document.querySelector('div[data-testid="sidebar"]');
                        
                        // Check for chat items
                        const chats = document.querySelectorAll('div[data-testid="chat"]');
                        results.chatCount = chats.length;
                        
                        // Check for search box
                        results.search = !!document.querySelector('div[data-testid="chat-list-search"]');
                        
                        // Check for any list items in sidebar
                        const listItems = document.querySelectorAll('div[role="listitem"]');
                        results.listItemCount = listItems.length;
                        
                        // Check for main panel content
                        const app = document.querySelector('div#app');
                        if (app) {
                            const hasQR = app.querySelector('div[data-ref]');
                            results.hasQRInApp = !!hasQR;
                            if (!hasQR) {
                                const hasContent = app.querySelector('div[class*="chat"], div[class*="panel"], div[class*="pane"]');
                                results.hasContent = !!hasContent;
                            }
                        }
                        
                        // Check for loading indicator (might be authenticating)
                        results.isLoading = !!document.querySelector('[data-testid="loading"]');
                        
                        // Check URL - if we're on the main WhatsApp Web page (not login), we're likely authenticated
                        const url = window.location.href;
                        results.onMainPage = url.includes('web.whatsapp.com') && !url.includes('login');
                        
                        // Determine if authenticated
                        const isAuthenticated = (
                            results.chatlist || 
                            (results.sidebar && !results.hasQRInApp) ||
                            results.chatCount > 0 ||
                            results.search ||
                            (results.listItemCount > 0 && !results.hasQRInApp) ||
                            (results.hasContent && !results.hasQRInApp && results.onMainPage)
                        );
                        
                        return {
                            authenticated: isAuthenticated,
                            indicators: results,
                            summary: isAuthenticated ? 'AUTHENTICATED' : 'NOT_AUTHENTICATED'
                        };
                    }
                """)
                
                logger.debug(f"QR code exists: {qr_exists}, Auth check: {auth_indicators.get('summary', 'UNKNOWN')}")
                
                # If we have auth indicators and no QR code, we're authenticated
                if auth_indicators.get('authenticated') and not qr_exists:
                    if not self.is_connected:
                        logger.info(f"✓ Authentication detected via JavaScript: {auth_indicators.get('indicators', {})}")
                    self.is_connected = True
                    self.qr_code = None
                    self.qr_code_base64 = None
                    self.qr_code_timestamp = None
                    self.has_session = True
                    await self._save_session()
                    return True
                
                # If QR code exists, we're definitely not authenticated
                if qr_exists:
                    logger.debug("QR code still visible - not authenticated")
                    return False
                    
            except Exception as e:
                logger.warning(f"Error in JavaScript auth check: {e}")
            
            # Fallback: Traditional selector-based checks
            # Method 1: Check for chat list
            try:
                chat_list = await self.page.query_selector('div[data-testid="chatlist"]')
                if chat_list:
                    if not self.is_connected:
                        logger.info("✓ Authentication detected: Chat list found")
                    self.is_connected = True
                    self.qr_code = None
                    self.qr_code_base64 = None
                    self.qr_code_timestamp = None
                    self.has_session = True
                    await self._save_session()
                    return True
            except Exception as e:
                logger.debug(f"Error checking chat list: {e}")
            
            # Method 2: Check for sidebar
            try:
                sidebar = await self.page.query_selector('div[data-testid="sidebar"]')
                if sidebar:
                    qr_code_elem = await self.page.query_selector('div[data-ref] canvas, div[data-ref] img')
                    if not qr_code_elem:
                        if not self.is_connected:
                            logger.info("✓ Authentication detected: Sidebar found without QR code")
                        self.is_connected = True
                        self.qr_code = None
                        self.qr_code_base64 = None
                        self.qr_code_timestamp = None
                        self.has_session = True
                        await self._save_session()
                        return True
            except Exception as e:
                logger.debug(f"Error checking sidebar: {e}")
            
            # Method 3: Check for chat items
            try:
                chat_items = await self.page.query_selector_all('div[data-testid="chat"]')
                if len(chat_items) > 0:
                    if not self.is_connected:
                        logger.info(f"✓ Authentication detected: Found {len(chat_items)} chat items")
                    self.is_connected = True
                    self.qr_code = None
                    self.qr_code_base64 = None
                    self.qr_code_timestamp = None
                    self.has_session = True
                    await self._save_session()
                    return True
            except Exception as e:
                logger.debug(f"Error checking chat items: {e}")
            
            # Method 4: Check page title - WhatsApp Web title changes when logged in
            try:
                title = await self.page.title()
                logger.debug(f"Page title: {title}")
                # When logged in, title is usually "WhatsApp" or contains "WhatsApp"
                # When not logged in, it might say "WhatsApp Web" or similar
                if title and 'WhatsApp' in title and 'Web' not in title:
                    # Check one more time for QR code to be sure
                    qr_check = await self.page.evaluate('document.querySelector("div[data-ref]") === null')
                    if qr_check:
                        if not self.is_connected:
                            logger.info("✓ Authentication detected: Page title indicates logged in")
                        self.is_connected = True
                        self.qr_code = None
                        self.qr_code_base64 = None
                        self.qr_code_timestamp = None
                        self.has_session = True
                        await self._save_session()
                        return True
            except Exception as e:
                logger.debug(f"Error checking page title: {e}")
            
            logger.debug("Authentication check: Not authenticated (no indicators found)")
            return False
            
        except Exception as e:
            logger.error(f"Error checking auth status: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def _update_qr_code(self, force_refresh=False):
        """Update QR code from WhatsApp Web"""
        try:
            # If we already have a QR code and it's less than 20 seconds old, don't refresh
            if not force_refresh and self.qr_code_base64 and self.qr_code_timestamp:
                age_seconds = (datetime.now() - self.qr_code_timestamp).total_seconds()
                if age_seconds < 20:  # QR codes are valid for ~20 seconds
                    logger.debug(f"QR code is still valid (age: {age_seconds:.1f}s), not refreshing")
                    return
            
            # Wait a bit for page to fully load
            await asyncio.sleep(3)
            
            # Try to find the QR code container first
            qr_container_selectors = [
                'div[data-ref]',
                'div._2EZ_m',
                'div[role="button"]',
                'div.qr-wrapper',
                'div[class*="qr"]'
            ]
            
            qr_container = None
            for selector in qr_container_selectors:
                try:
                    qr_container = await self.page.wait_for_selector(selector, timeout=3000)
                    if qr_container:
                        break
                except:
                    continue
            
            # Try multiple selectors for QR code canvas/image
            qr_selectors = [
                'div[data-ref] canvas',
                'div[data-ref] img',
                'canvas[aria-label*="QR"]',
                'div._2EZ_m canvas',
                'div[role="button"] canvas',
                'div.qr-wrapper canvas',
                'canvas'
            ]
            
            qr_element = None
            qr_data = None
            
            for selector in qr_selectors:
                try:
                    qr_element = await self.page.wait_for_selector(selector, timeout=3000)
                    if qr_element:
                        # Try to get QR code data from data-ref attribute (parent or self)
                        qr_data = await qr_element.get_attribute('data-ref')
                        if not qr_data and qr_container:
                            qr_data = await qr_container.get_attribute('data-ref')
                        if not qr_data:
                            # Try to get from parent element
                            try:
                                parent = await qr_element.evaluate_handle('el => el.parentElement')
                                if parent:
                                    qr_data = await parent.get_attribute('data-ref')
                            except:
                                pass
                        
                        if qr_element:
                            break
                except:
                    continue
            
            # If we found QR element, get screenshot
            if qr_element:
                try:
                    # Get the bounding box to ensure we capture the full QR code
                    box = await qr_element.bounding_box()
                    if box:
                        # Take screenshot with high quality settings
                        screenshot = await qr_element.screenshot(
                            type='png',
                            omit_background=False
                        )
                        img_str = base64.b64encode(screenshot).decode()
                        self.qr_code_base64 = f"data:image/png;base64,{img_str}"
                        self.qr_code_timestamp = datetime.now()
                        logger.info(f"QR code screenshot captured (size: {len(screenshot)} bytes)")
                        
                        # Also try to extract QR data if available
                        if qr_data:
                            self.qr_code = qr_data
                            logger.info(f"QR code data extracted: {qr_data[:50] if len(qr_data) > 50 else qr_data}...")
                    else:
                        # Fallback: try container screenshot
                        if qr_container:
                            screenshot = await qr_container.screenshot(
                                type='png',
                                omit_background=False
                            )
                            img_str = base64.b64encode(screenshot).decode()
                            self.qr_code_base64 = f"data:image/png;base64,{img_str}"
                            self.qr_code_timestamp = datetime.now()
                            logger.info(f"QR code screenshot captured from container (size: {len(screenshot)} bytes)")
                except Exception as e:
                    logger.warning(f"Could not take QR code screenshot: {e}")
                    # Fallback: try to generate QR from data-ref if available
                    if qr_data:
                        try:
                            import qrcode
                            from io import BytesIO
                            
                            qr = qrcode.QRCode(version=1, box_size=10, border=5)
                            qr.add_data(qr_data)
                            qr.make(fit=True)
                            
                            img = qr.make_image(fill_color="black", back_color="white")
                            buffered = BytesIO()
                            img.save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()
                            self.qr_code_base64 = f"data:image/png;base64,{img_str}"
                            self.qr_code = qr_data
                            self.qr_code_timestamp = datetime.now()
                            logger.info("QR code generated from data-ref")
                        except Exception as e2:
                            logger.warning(f"Could not generate QR code from data: {e2}")
                            self.qr_code_base64 = None
                            self.qr_code_timestamp = None
                    else:
                        self.qr_code_base64 = None
                        self.qr_code_timestamp = None
            else:
                logger.warning("QR code element not found with any selector")
                self.qr_code = None
                self.qr_code_base64 = None
                self.qr_code_timestamp = None
        except Exception as e:
            logger.error(f"Error updating QR code: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.qr_code = None
            self.qr_code_base64 = None
            self.qr_code_timestamp = None
    
    async def _save_session(self):
        """Save browser session state"""
        try:
            if self.context and self.page:
                storage_file = os.path.join(self.session_path, 'storage_state.json')
                # Save storage state (cookies, localStorage, etc.)
                await self.context.storage_state(path=storage_file)
                logger.info(f"WhatsApp session saved to {storage_file}")
                
                # Also save cookies explicitly as backup
                cookies = await self.context.cookies()
                cookies_file = os.path.join(self.session_path, 'cookies.json')
                with open(cookies_file, 'w') as f:
                    import json
                    json.dump(cookies, f, indent=2)
                logger.info(f"Cookies saved to {cookies_file}")
                
                # Update has_session flag
                self.has_session = True
        except Exception as e:
            logger.warning(f"Could not save session: {e}")
            import traceback
            logger.warning(traceback.format_exc())
    
    async def cleanup(self):
        """Cleanup WhatsApp client"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.is_connected = False
            logger.info("WhatsApp service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up WhatsApp service: {e}")
    
    async def _monitor_authentication(self):
        """Monitor for authentication after QR code is displayed"""
        logger.info("Starting authentication monitoring...")
        max_attempts = 300  # Monitor for up to 5 minutes (300 * 1 second)
        attempts = 0
        last_qr_check = True
        last_url = None
        
        while attempts < max_attempts and not self.is_connected:
            try:
                await asyncio.sleep(1)  # Check every second
                attempts += 1
                
                # Check URL change (WhatsApp Web redirects after authentication)
                try:
                    current_url = self.page.url
                    if last_url and current_url != last_url:
                        logger.info(f"URL changed: {last_url} -> {current_url} - might indicate authentication")
                        # Wait a moment for page to update
                        await asyncio.sleep(2)
                        # Immediately check authentication
                        is_authenticated = await self._check_authentication_status()
                        if is_authenticated:
                            logger.info("✓ Authentication detected after URL change! Session saved.")
                            break
                    last_url = current_url
                except:
                    pass
                
                # Check if QR code still exists (if it disappears, user might be authenticating)
                try:
                    qr_still_exists = await self.page.evaluate('document.querySelector("div[data-ref]") !== null')
                    if last_qr_check and not qr_still_exists:
                        logger.info("⚠️ QR code disappeared - user might be authenticating, checking immediately...")
                        # Wait a bit for page to update
                        await asyncio.sleep(3)
                        # Check authentication immediately
                        is_authenticated = await self._check_authentication_status()
                        if is_authenticated:
                            logger.info("✓ Authentication detected after QR code disappeared! Session saved.")
                            break
                    last_qr_check = qr_still_exists
                except Exception as e:
                    logger.debug(f"Error checking QR code: {e}")
                
                # Check if authenticated (regular check)
                is_authenticated = await self._check_authentication_status()
                if is_authenticated:
                    logger.info("✓ Authentication detected during monitoring! Session saved.")
                    break
                
                # Log progress every 10 seconds
                if attempts % 10 == 0:
                    logger.info(f"Monitoring authentication... ({attempts}/{max_attempts} seconds) - QR visible: {last_qr_check}")
                    # Also log current page state for debugging
                    try:
                        page_state = await self.page.evaluate("""
                            () => {
                                return {
                                    url: window.location.href,
                                    hasQR: document.querySelector('div[data-ref]') !== null,
                                    hasChatList: document.querySelector('div[data-testid="chatlist"]') !== null,
                                    chatCount: document.querySelectorAll('div[data-testid="chat"]').length
                                };
                            }
                        """)
                        logger.debug(f"Page state: {page_state}")
                    except:
                        pass
                    
            except Exception as e:
                logger.warning(f"Error in authentication monitoring: {e}")
                # Don't break, continue monitoring
                continue
        
        if attempts >= max_attempts and not self.is_connected:
            logger.warning("Authentication monitoring stopped (timeout after 5 minutes)")
            logger.info("Tip: If you scanned the QR code, try clicking 'Refresh' button to check authentication status")
        elif self.is_connected:
            logger.info("✓ Authentication monitoring completed successfully")
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check WhatsApp connection status
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        if not PLAYWRIGHT_AVAILABLE:
            return False, "Playwright not installed. Install with: pip install playwright && playwright install chromium"
        
        if not self.page:
            # Try to initialize
            try:
                await self.initialize()
            except Exception as e:
                logger.error(f"Error initializing WhatsApp: {e}")
                return False, f"Error initializing: {str(e)}"
        
        # Check current status
        try:
            # Always check authentication status first
            is_authenticated = await self._check_authentication_status()
            
            if is_authenticated:
                if not self.is_connected:
                    logger.info("✓ User authenticated - session saved")
                # Ensure QR code is cleared
                self.qr_code = None
                self.qr_code_base64 = None
                self.qr_code_timestamp = None
            elif not self.is_connected:
                # Only update QR code if we don't have one and not connected
                if not self.qr_code_base64:
                    logger.info("No QR code available, attempting to get one...")
                    # Try to update QR code
                    await self._update_qr_code()
        except Exception as e:
            logger.error(f"Error checking status: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        if self.is_connected:
            return True, "Connected to WhatsApp"
        elif self.qr_code_base64:
            return False, "QR code authentication required"
        else:
            return False, "Not connected. Please click Refresh to start authentication."
    
    async def get_qr_code(self, force_refresh=False) -> Optional[str]:
        """
        Get QR code for authentication
        
        Args:
            force_refresh: Force refresh of QR code even if one exists
        
        Returns:
            Base64 encoded QR code image or None
        """
        if not PLAYWRIGHT_AVAILABLE:
            return None
        
        if self.is_connected:
            return None  # Already authenticated
        
        # Try to initialize if not already done
        if not self.page:
            await self.initialize()
        elif force_refresh:
            # Only refresh if explicitly requested
            try:
                await self.page.reload(wait_until='domcontentloaded')
                await asyncio.sleep(3)
                await self._update_qr_code(force_refresh=True)
            except Exception as e:
                logger.warning(f"Error refreshing page for QR code: {e}")
                await self._update_qr_code(force_refresh=True)
        elif not self.qr_code_base64:
            # Only update if we don't have a QR code
            await self._update_qr_code()
        
        return self.qr_code_base64
    
    async def get_contacts(self) -> List[WhatsAppContact]:
        """
        Retrieve all WhatsApp contacts
        
        Returns:
            List of WhatsApp contacts
        """
        try:
            if not PLAYWRIGHT_AVAILABLE:
                raise Exception("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            
            if not self.page:
                raise Exception("WhatsApp client not initialized")
            
            # Verify connection first
            if not self.is_connected:
                logger.info("Not connected, checking authentication status...")
                # Wait a bit for page to settle
                await asyncio.sleep(2)
                await self._check_authentication_status()
                if not self.is_connected:
                    logger.error("WhatsApp client not connected. Authentication required.")
                    raise Exception("WhatsApp client not connected. Please scan the QR code to authenticate first.")
            
            logger.info("WhatsApp is connected, fetching contacts...")
            
            # Navigate to WhatsApp Web if not already there
            current_url = self.page.url
            if 'web.whatsapp.com' not in current_url:
                logger.info("Not on WhatsApp Web, navigating...")
                await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=30000)
                await asyncio.sleep(5)  # Wait longer for page to fully load
                # Verify we're still connected after navigation
                await self._check_authentication_status()
                if not self.is_connected:
                    raise Exception("Lost connection after navigation. Please authenticate again.")
            else:
                # Already on WhatsApp Web, wait for it to be ready
                logger.info("Already on WhatsApp Web, waiting for page to be ready...")
                try:
                    await self.page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
                await asyncio.sleep(3)  # Give WhatsApp time to fully load
            
            # Wait for chat list to load - try multiple selectors with longer timeout
            chat_list_loaded = False
            selectors_to_try = [
                'div[data-testid="chatlist"]',
                'div[data-testid="chat"]',
                'div[role="listitem"]',
                'div#pane-side',
                'div[class*="chat"]',
                'div[class*="pane"]',
                'div[role="list"]'
            ]
            
            logger.info("Waiting for chat list to load...")
            
            # First, wait for the main app to be ready
            try:
                await self.page.wait_for_selector('div#app', timeout=15000)
                logger.info("Main app container found")
            except:
                logger.warning("Main app container not found")
            
            # Wait for network to be idle
            try:
                await self.page.wait_for_load_state('networkidle', timeout=10000)
                logger.info("Page network idle")
            except:
                logger.debug("Network not idle, continuing anyway")
            
            # Wait a bit for WhatsApp to fully initialize
            await asyncio.sleep(3)
            
            # Now try to find chat list
            for selector in selectors_to_try:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=5000, state='attached')
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            # Check if it has content
                            child_count = await self.page.evaluate(f"""
                                () => {{
                                    const elem = document.querySelector('{selector}');
                                    return elem ? elem.children.length : 0;
                                }}
                            """)
                            if child_count > 0 or selector == 'div[data-testid="chatlist"]':
                                chat_list_loaded = True
                                logger.info(f"Chat list loaded using selector: {selector} (children: {child_count})")
                                break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue
            
            if not chat_list_loaded:
                # Try to get page state for debugging
                try:
                    page_state = await self.page.evaluate("""
                        () => {
                            const selectors = [
                                'div#app',
                                'div[data-testid="chatlist"]',
                                'div[data-testid="chat"]',
                                'div#pane-side',
                                'div[role="listitem"]',
                                'div[data-ref]'
                            ];
                            const state = {
                                url: window.location.href,
                                title: document.title,
                                selectors: {}
                            };
                            selectors.forEach(sel => {
                                const elem = document.querySelector(sel);
                                state.selectors[sel] = {
                                    exists: !!elem,
                                    visible: elem ? elem.offsetParent !== null : false,
                                    children: elem ? elem.children.length : 0
                                };
                            });
                            return state;
                        }
                    """)
                    logger.error(f"Chat list not loaded. Page state: {json.dumps(page_state, indent=2)}")
                except Exception as e:
                    logger.error(f"Could not get page state: {e}")
                
                # Check if we're actually authenticated
                is_auth = await self._check_authentication_status()
                if not is_auth:
                    raise Exception("Not authenticated. Please scan the QR code first.")
                else:
                    raise Exception("Authenticated but chat list not loading. The page may still be initializing. Please wait a moment and try again.")
            
            # Wait a bit for chats to render
            logger.info("Waiting for chats to render...")
            await asyncio.sleep(2)
            
            # Use JavaScript to extract contacts directly from DOM (more reliable)
            # Try multiple times with scrolling to load more contacts
            contacts_data = []
            max_retries = 3
            
            for retry in range(max_retries):
                try:
                    # Scroll to top first, then scroll down to load chats
                    await self.page.evaluate("""
                        () => {
                            const chatList = document.querySelector('div[data-testid="chatlist"]') || 
                                           document.querySelector('div#pane-side') ||
                                           document.querySelector('div[role="list"]');
                            if (chatList) {
                                chatList.scrollTop = 0;
                            }
                        }
                    """)
                    await asyncio.sleep(1)
                    
                    # Scroll down to load more
                    await self.page.evaluate("""
                        () => {
                            const chatList = document.querySelector('div[data-testid="chatlist"]') || 
                                           document.querySelector('div#pane-side') ||
                                           document.querySelector('div[role="list"]');
                            if (chatList) {
                                chatList.scrollTop = chatList.scrollHeight;
                            }
                        }
                    """)
                    await asyncio.sleep(2)
                    
                    contacts_data = await self.page.evaluate("""
                        () => {
                            const contacts = [];
                            const seen = new Set();
                            
                            // Try multiple selectors for chat items
                            const chatSelectors = [
                                'div[data-testid="chat"]',
                                'div[role="listitem"]',
                                'div[class*="chat"]'
                            ];
                            
                            let chatItems = [];
                            for (let selector of chatSelectors) {
                                chatItems = Array.from(document.querySelectorAll(selector));
                                if (chatItems.length > 0) break;
                            }
                            
                            chatItems.forEach((item, index) => {
                                try {
                                    // Get contact name
                                    const nameElement = item.querySelector('span[title]') || 
                                                       item.querySelector('span[class*="title"]') ||
                                                       item.querySelector('div[class*="title"]') ||
                                                       item.querySelector('span');
                                    
                                    if (!nameElement) return;
                                    
                                    const contactName = nameElement.getAttribute('title') || 
                                                      nameElement.textContent?.trim() || '';
                                    
                                    if (!contactName || contactName.length < 1) return;
                                    if (seen.has(contactName)) return;
                                    seen.add(contactName);
                                    
                                    // Try to get contact ID from data attributes
                                    let contactId = item.getAttribute('data-id') || 
                                                   item.getAttribute('data-chat-id') ||
                                                   item.getAttribute('id') ||
                                                   `contact_${index}`;
                                    
                                    // Check if it's a group
                                    const isGroup = item.querySelector('[data-testid="group"]') !== null ||
                                                  item.querySelector('[data-icon="group"]') !== null ||
                                                  contactName.toLowerCase().includes('group') ||
                                                  item.getAttribute('data-group') === 'true';
                                    
                                    // Extract phone number if available
                                    let phoneNumber = '';
                                    const phoneMatch = contactId.match(/\\d+/);
                                    if (phoneMatch) {
                                        phoneNumber = phoneMatch[0];
                                    } else {
                                        phoneNumber = contactName.replace(/[^0-9]/g, '');
                                    }
                                    
                                    contacts.push({
                                        contact_id: contactId,
                                        name: contactName,
                                        phone_number: phoneNumber || contactId,
                                        is_group: isGroup
                                    });
                                } catch (e) {
                                    console.error('Error processing contact:', e);
                                }
                            });
                            
                            return contacts;
                        }
                    """)
                    
                    if len(contacts_data) > 0:
                        logger.info(f"Found {len(contacts_data)} contacts on attempt {retry + 1}")
                        break
                    else:
                        logger.info(f"No contacts found on attempt {retry + 1}, retrying...")
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"Error extracting contacts on attempt {retry + 1}: {e}")
                    if retry < max_retries - 1:
                        await asyncio.sleep(2)
                    else:
                        raise
            
            contacts = []
            for contact_data in contacts_data:
                try:
                    # Normalize contact ID
                    contact_id = contact_data.get('contact_id', '')
                    if not contact_id.startswith('+') and '@' not in contact_id:
                        # Generate a proper ID
                        phone = contact_data.get('phone_number', '')
                        if phone:
                            contact_id = f"{phone}@c.us" if not contact_data.get('is_group') else f"{phone}@g.us"
                        else:
                            # Use name-based ID
                            name = contact_data.get('name', '').replace(' ', '').lower()
                            contact_id = f"{name}@c.us" if not contact_data.get('is_group') else f"{name}@g.us"
                    
                    contacts.append(WhatsAppContact(
                        contact_id=contact_id,
                        name=contact_data.get('name', 'Unknown'),
                        phone_number=contact_data.get('phone_number', ''),
                        is_group=contact_data.get('is_group', False)
                    ))
                except Exception as e:
                    logger.warning(f"Error creating contact object: {e}")
                    continue
            
            if len(contacts) == 0:
                logger.warning("No contacts found. Trying alternative method...")
                # Fallback: try to get contacts by scrolling and collecting visible chats
                try:
                    # Scroll to load more chats
                    await self.page.evaluate("""
                        () => {
                            const chatList = document.querySelector('div[data-testid="chatlist"]') || 
                                           document.querySelector('div#pane-side');
                            if (chatList) {
                                chatList.scrollTop = 0;
                                setTimeout(() => {
                                    chatList.scrollTop = chatList.scrollHeight;
                                }, 500);
                            }
                        }
                    """)
                    await asyncio.sleep(2)
                    
                    # Try again with the same method
                    contacts_data = await self.page.evaluate("""
                        () => {
                            const contacts = [];
                            const seen = new Set();
                            const chatItems = Array.from(document.querySelectorAll('div[data-testid="chat"], div[role="listitem"]'));
                            
                            chatItems.slice(0, 50).forEach((item) => {
                                try {
                                    const nameElement = item.querySelector('span[title]') || item.querySelector('span');
                                    if (!nameElement) return;
                                    
                                    const name = nameElement.getAttribute('title') || nameElement.textContent?.trim() || '';
                                    if (!name || seen.has(name)) return;
                                    seen.add(name);
                                    
                                    contacts.push({
                                        contact_id: `contact_${contacts.length}`,
                                        name: name,
                                        phone_number: '',
                                        is_group: false
                                    });
                                } catch (e) {}
                            });
                            
                            return contacts;
                        }
                    """)
                    
                    for contact_data in contacts_data:
                        contact_id = f"{contact_data.get('name', '').replace(' ', '').lower()}@c.us"
                        contacts.append(WhatsAppContact(
                            contact_id=contact_id,
                            name=contact_data.get('name', 'Unknown'),
                            phone_number=contact_data.get('phone_number', ''),
                            is_group=contact_data.get('is_group', False)
                        ))
                except Exception as fallback_error:
                    logger.warning(f"Fallback method also failed: {fallback_error}")
            
            logger.info(f"Retrieved {len(contacts)} WhatsApp contacts")
            return contacts
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching WhatsApp contacts: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            raise Exception(f"Failed to fetch contacts: {error_msg}")
    
    async def get_messages(
        self,
        contact_id: Optional[str] = None,
        limit: int = 50
    ) -> Tuple[List[WhatsAppMessage], int]:
        """
        Retrieve WhatsApp messages
        
        Args:
            contact_id: Optional contact ID to get messages for a specific contact
            limit: Maximum number of messages to retrieve
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            if not PLAYWRIGHT_AVAILABLE:
                raise Exception("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            
            if not self.page:
                raise Exception("WhatsApp client not initialized")
            
            if not self.is_connected:
                await self._check_authentication_status()
                if not self.is_connected:
                    raise Exception("WhatsApp client not connected. Please authenticate first.")
            
            messages = []
            
            if contact_id:
                # Navigate to specific contact
                phone_number = contact_id.replace('@c.us', '').replace('@g.us', '')
                chat_url = f'https://web.whatsapp.com/send?phone={phone_number}'
                await self.page.goto(chat_url, wait_until='networkidle')
                await asyncio.sleep(2)
                
                # Wait for messages to load
                try:
                    await self.page.wait_for_selector('div[data-testid="conversation-panel-messages"]', timeout=10000)
                except:
                    # Try alternative selector
                    await self.page.wait_for_selector('div.message', timeout=5000)
                
                # Get contact name
                try:
                    header = await self.page.query_selector('div[data-testid="conversation-header"]')
                    if header:
                        name_element = await header.query_selector('span[title]')
                        contact_name = await name_element.get_attribute('title') if name_element else ''
                    else:
                        contact_name = phone_number
                except:
                    contact_name = phone_number
                
                # Get all message elements
                message_elements = await self.page.query_selector_all('div[data-testid="msg-container"]')
                
                for msg_element in message_elements[:limit]:
                    try:
                        # Get message text
                        text_element = await msg_element.query_selector('span.selectable-text')
                        body = ''
                        if text_element:
                            body = await text_element.inner_text()
                        
                        # Check if message is sent by user
                        is_sent = False
                        message_wrapper = await msg_element.query_selector('div.message')
                        if message_wrapper:
                            classes = await message_wrapper.get_attribute('class') or ''
                            is_sent = 'message-out' in classes or 'message-sent' in classes
                        
                        # Get timestamp
                        time_element = await msg_element.query_selector('span[data-testid="msg-time"]')
                        timestamp_str = ''
                        if time_element:
                            timestamp_str = await time_element.inner_text()
                        
                        # Generate message ID
                        message_id = f"{contact_id}_{len(messages)}"
                        
                        # Parse timestamp (simplified - WhatsApp shows time like "10:30 AM")
                        date_obj = datetime.now()  # Default to now
                        try:
                            # Try to parse time if available
                            if timestamp_str:
                                # This is a simplified parser - in production, you'd want more robust parsing
                                pass
                        except:
                            pass
                        
                        messages.append(WhatsAppMessage(
                            message_id=message_id,
                            from_id=contact_id,
                            from_name=contact_name if not is_sent else 'You',
                            body=body,
                            timestamp=date_obj.isoformat(),
                            is_sent=is_sent,
                            contact_id=contact_id,
                            contact_name=contact_name
                        ))
                    except Exception as e:
                        logger.warning(f"Error processing message: {e}")
                        continue
                
                # Reverse to show oldest first (or keep newest first)
                messages.reverse()
            else:
                # Get messages from all chats (simplified - get from chat list)
                # This is more complex, so we'll just return empty for now
                # In production, you'd iterate through contacts
                pass
            
            total_count = len(messages)
            logger.info(f"Retrieved {total_count} WhatsApp messages")
            return messages, total_count
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching WhatsApp messages: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            raise Exception(error_msg)
    
    async def send_message(
        self,
        contact_id: str,
        text: str
    ) -> str:
        """
        Send a message to a WhatsApp contact
        
        Args:
            contact_id: The contact ID to send the message to
            text: The message text to send
        
        Returns:
            Message ID of the sent message
        """
        try:
            if not PLAYWRIGHT_AVAILABLE:
                raise Exception("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            
            if not self.page:
                raise Exception("WhatsApp client not initialized")
            
            if not self.is_connected:
                await self._check_authentication_status()
                if not self.is_connected:
                    raise Exception("WhatsApp client not connected. Please authenticate first.")
            
            logger.info(f"Sending message to contact {contact_id}")
            
            # Navigate to contact
            phone_number = contact_id.replace('@c.us', '').replace('@g.us', '')
            chat_url = f'https://web.whatsapp.com/send?phone={phone_number}'
            await self.page.goto(chat_url, wait_until='networkidle')
            await asyncio.sleep(2)
            
            # Find message input box
            input_selector = 'div[data-testid="conversation-compose-box-input"], div[contenteditable="true"][data-testid="text-box"]'
            input_box = await self.page.wait_for_selector(input_selector, timeout=10000)
            
            # Type message
            await input_box.fill(text)
            await asyncio.sleep(0.5)
            
            # Send message (press Enter or click send button)
            send_button = await self.page.query_selector('button[data-testid="send"]')
            if send_button:
                await send_button.click()
            else:
                await input_box.press('Enter')
            
            await asyncio.sleep(1)
            
            # Generate message ID
            message_id = f"{contact_id}_{int(time.time())}"
            logger.info(f"Successfully sent WhatsApp message. Message ID: {message_id}")
            return message_id
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error sending WhatsApp message: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            raise Exception(error_msg)

