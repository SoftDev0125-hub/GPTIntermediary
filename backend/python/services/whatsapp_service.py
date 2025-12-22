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


logger = logging.getLogger(__name__)


class WhatsAppService:
    """
    Service for handling WhatsApp operations using Playwright
    """
    
    def __init__(self):
        """Initialize WhatsApp service"""
        load_dotenv(override=True)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_connected = False
        self.session_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'whatsapp_session')
        os.makedirs(self.session_path, exist_ok=True)
        self._initializing = False  # Flag to prevent multiple simultaneous initializations
        
        # Check if session exists - this is critical for auto-reconnection
        self.has_session = self._check_session_exists()
        
        if self.has_session:
            logger.info("✓ Existing WhatsApp session detected - will auto-connect on initialization")
        else:
            logger.info("No existing WhatsApp session - authentication will be required")
        
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available. Install with: pip install playwright && playwright install chromium")
        else:
            logger.info("WhatsApp service initialized")
    
    def _check_session_exists(self) -> bool:
        """Check if WhatsApp session files exist and are valid"""
        storage_state_path = os.path.join(self.session_path, 'storage_state.json')
        
        # Check if storage state file exists and has WhatsApp data
        if not os.path.exists(storage_state_path):
            logger.debug(f"Session file does not exist at {storage_state_path}")
            return False
        
        try:
            with open(storage_state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # More lenient validation: if file exists and has valid JSON structure, accept it
            # Playwright's storage_state format should have 'cookies' and 'origins' keys
            if not isinstance(data, dict):
                logger.warning("Session file exists but doesn't contain valid JSON object")
                return False
            
            has_whatsapp_data = False
            
            # Check for WhatsApp-specific localStorage data (preferred)
            origins = data.get('origins', [])
            for origin in origins:
                if origin.get('origin') == 'https://web.whatsapp.com':
                    localStorage = origin.get('localStorage', [])
                    if localStorage:
                        # Check for WhatsApp session keys (if present, this is a strong indicator)
                        for item in localStorage:
                            if item.get('name') in ['WABrowserId', 'WAWebVersion', 'WASecretBundle']:
                                logger.info("WhatsApp session keys found in storage state")
                                return True
                        # If we have localStorage for WhatsApp Web, that's good enough
                        if len(localStorage) > 0:
                            logger.info(f"WhatsApp localStorage found ({len(localStorage)} items)")
                            has_whatsapp_data = True
            
            # Check cookies (fallback - WhatsApp Web always has cookies when authenticated)
            cookies = data.get('cookies', [])
            whatsapp_cookies = [c for c in cookies if 'whatsapp.com' in c.get('domain', '').lower()]
            
            # Filter out expired cookies - only count valid cookies
            from datetime import datetime, timezone
            valid_whatsapp_cookies = []
            for cookie in whatsapp_cookies:
                # Check if cookie has expiration
                if 'expires' in cookie:
                    try:
                        # Expires can be a timestamp or datetime
                        expires = cookie.get('expires')
                        if isinstance(expires, (int, float)):
                            # Unix timestamp
                            if expires > time.time():
                                valid_whatsapp_cookies.append(cookie)
                        elif isinstance(expires, str):
                            # Try to parse as datetime
                            try:
                                exp_date = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                                if exp_date > datetime.now(timezone.utc):
                                    valid_whatsapp_cookies.append(cookie)
                            except:
                                # If we can't parse, assume it's valid
                                valid_whatsapp_cookies.append(cookie)
                    except Exception as e:
                        logger.debug(f"Error checking cookie expiration: {e}")
                        # If we can't check expiration, assume cookie is valid
                        valid_whatsapp_cookies.append(cookie)
                else:
                    # Session cookie (no expiration) - always valid
                    valid_whatsapp_cookies.append(cookie)
            
            if len(valid_whatsapp_cookies) >= 1:  # At least 1 valid cookie
                logger.info(f"WhatsApp session cookies found ({len(valid_whatsapp_cookies)} valid cookies out of {len(whatsapp_cookies)} total)")
                has_whatsapp_data = True
            
            # If we have either localStorage or cookies for WhatsApp, accept the session
            if has_whatsapp_data:
                logger.info("WhatsApp session data found - session file is valid")
                return True
            
            # If file exists but has no WhatsApp data, it might be from a different site or invalid
            # But to be safe, if the file exists and is valid JSON, accept it (very lenient fallback)
            if origins or cookies:
                logger.warning("Session file exists but doesn't contain clear WhatsApp data - accepting anyway (lenient mode)")
                return True
            
            logger.warning("Session file exists but appears empty or invalid")
            return False
            
        except json.JSONDecodeError as e:
            logger.warning(f"Session file exists but is not valid JSON: {e}")
            return False
        except Exception as e:
            logger.warning(f"Error checking session file: {e}")
            return False
    
    async def initialize(self):
        """Initialize WhatsApp client connection"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available. Cannot initialize WhatsApp service.")
            return
        
        # Prevent multiple simultaneous initializations
        if self._initializing:
            logger.debug("Initialization already in progress, skipping duplicate call")
            # Wait for existing initialization to complete (with timeout)
            max_wait = 120  # Wait up to 2 minutes
            waited = 0
            while self._initializing and waited < max_wait:
                await asyncio.sleep(1)
                waited += 1
            if waited >= max_wait:
                logger.warning("Initialization wait timed out - proceeding with new initialization")
            else:
                logger.debug("Waited for existing initialization to complete")
                return
        
        # If already initialized and connected, skip
        if self.is_connected and self.page and self.browser and self.context:
            logger.debug("Already initialized and connected, skipping re-initialization")
            return
        
        self._initializing = True
        try:
            if self.playwright is None:
                self.playwright = await async_playwright().start()
            
            # Load existing session if available
            # IMPORTANT: Re-check for session file here, even if has_session was False in __init__
            # This handles cases where the session file exists but wasn't detected initially
            storage_state_path = os.path.join(self.session_path, 'storage_state.json')
            storage_state = None
            
            # Check if session file exists (re-check, don't just rely on has_session flag)
            if os.path.exists(storage_state_path):
                try:
                    with open(storage_state_path, 'r', encoding='utf-8') as f:
                        storage_state = json.load(f)
                    
                    # Use the same validation logic as _check_session_exists
                    # If file exists and loaded successfully, use it (lenient validation)
                    if storage_state and isinstance(storage_state, dict):
                        # Check if it has basic structure
                        if storage_state.get('origins') or storage_state.get('cookies'):
                            logger.info(f"✓ Loading existing WhatsApp session from {storage_state_path}")
                            # Update has_session flag since we found a valid session
                            self.has_session = True
                            
                            # Log session details for debugging
                            origins_count = len(storage_state.get('origins', []))
                            cookies_count = len(storage_state.get('cookies', []))
                            whatsapp_cookies = [c for c in storage_state.get('cookies', []) if 'whatsapp.com' in c.get('domain', '').lower()]
                            logger.info(f"Session file contains: {origins_count} origins, {cookies_count} cookies ({len(whatsapp_cookies)} WhatsApp cookies)")
                        else:
                            logger.warning("Session file exists but appears empty")
                            storage_state = None
                            self.has_session = False
                    else:
                        logger.warning("Session file exists but doesn't contain valid data")
                        storage_state = None
                        self.has_session = False
                except Exception as e:
                    logger.warning(f"Error loading session file: {e}")
                    storage_state = None
                    self.has_session = False  # Mark as no session if file is invalid
            else:
                # No session file exists - check if there's an expired one and clean it up
                expired_path = storage_state_path + '.expired'
                if os.path.exists(expired_path):
                    logger.debug(f"Found expired session file: {expired_path}")
                self.has_session = False
            
            # Launch browser in headless mode (no visible window)
            if self.browser is None:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,  # Run in background - no visible browser window
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--no-sandbox',
                        '--disable-setuid-sandbox'
                    ]
                )
            
            # Create context with or without session
            # If we have a session file (storage_state) and context already exists, recreate it with the session
            # This ensures the session is properly loaded even if context was created before
            if storage_state and self.context is not None:
                logger.info("Session file found - recreating browser context with session data")
                try:
                    await self.context.close()
                except Exception as e:
                    logger.warning(f"Error closing old context: {e}")
                self.context = None
                self.page = None  # Page will be recreated below
            
            if self.context is None:
                context_options = {
                    'viewport': {'width': 1280, 'height': 720},
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'device_scale_factor': 1,
                    'has_touch': False,
                    'is_mobile': False
                }
                if storage_state:
                    context_options['storage_state'] = storage_state
                    logger.info("✓ Creating browser context WITH session data (auto-reconnect enabled)")
                else:
                    logger.info("Creating browser context WITHOUT session data (authentication will be required)")
                
                self.context = await self.browser.new_context(**context_options)
                
                # Log confirmation that context was created
                if storage_state:
                    logger.info("✓ Browser context created successfully with session - WhatsApp should auto-connect")
            
            # Create page
            if self.page is None:
                self.page = await self.context.new_page()
            
            # Navigate to WhatsApp Web
            logger.info("Navigating to WhatsApp Web...")
            await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=60000)
            
            # Wait longer for page to fully load, especially if we have a session
            if self.has_session:
                logger.info("Session exists - waiting longer for WhatsApp Web to restore session...")
                logger.info("This may take 30-60 seconds for WhatsApp Web to fully restore the session...")
                
                # Wait for the page to be interactive
                try:
                    # Wait for the app div to be present
                    await self.page.wait_for_selector('div#app', timeout=20000)
                    logger.info("App div found - waiting for content to load...")
                except Exception as e:
                    logger.warning(f"Timeout waiting for app div: {e}")
                
                # Initial wait for page to settle - WhatsApp Web needs time to process session
                await asyncio.sleep(8)  # Increased wait time for session restoration
                
                # Try to wait for authenticated content (chat list) - this is what we want
                # Don't wait for QR code - if session is valid, we shouldn't see QR code
                try:
                    # Wait for authenticated content with longer timeout
                    await self.page.wait_for_function("""
                        () => {
                            const hasChatlist = !!document.querySelector('div[data-testid="chatlist"]');
                            const hasChats = document.querySelectorAll('div[data-testid="chat"]').length > 0;
                            const hasSidebar = !!document.querySelector('div[data-testid="sidebar"]');
                            const hasSearch = !!document.querySelector('div[data-testid="chat-list-search"]');
                            // Check for authenticated state indicators
                            return hasChatlist || hasChats || hasSidebar || hasSearch;
                        }
                    """, timeout=45000)  # Increased to 45 seconds - session restoration can be slow
                    logger.info("Authenticated content detected - session is restoring")
                except Exception as e:
                    logger.warning(f"Timeout waiting for authenticated content: {e}")
                    logger.info("Continuing anyway - will check authentication status...")
                
                # Additional wait for everything to settle
                await asyncio.sleep(5)  # Give WhatsApp Web more time to fully restore
                logger.info("Session restoration wait completed")
            else:
                await asyncio.sleep(2)
            
            # Check authentication status
            # If we have a session, give it more time to restore before checking
            if self.has_session:
                logger.info("Session exists - waiting for WhatsApp Web to restore authentication...")
                logger.info("This process can take up to 60 seconds - please be patient...")
                # Wait for WhatsApp Web to process the session - this is critical!
                # WhatsApp Web needs time to validate and restore the session from cookies/localStorage
                await asyncio.sleep(12)  # Increased wait time - session restoration is slow
                
                # Wait for authenticated state to appear using a more flexible approach
                logger.info("Waiting for authenticated state to appear...")
                try:
                    # Use wait_for_function to wait for ANY authenticated indicator
                    # This is more flexible than waiting for specific selectors
                    await self.page.wait_for_function("""
                        () => {
                            // Check for any authenticated state indicators
                            const hasChatlist = !!document.querySelector('div[data-testid="chatlist"]');
                            const hasChats = document.querySelectorAll('div[data-testid="chat"]').length > 0;
                            const hasSidebar = !!document.querySelector('div[data-testid="sidebar"]');
                            const hasSearch = !!document.querySelector('div[data-testid="chat-list-search"]');
                            const hasListItems = document.querySelectorAll('div[role="listitem"]').length > 0;
                            
                            // Check if QR code is NOT visible (if visible, we're not authenticated)
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            
                            // We're authenticated if we have any auth indicators AND no QR code
                            return (hasChatlist || hasChats || hasSidebar || hasSearch || hasListItems) && !hasQR;
                        }
                    """, timeout=30000)
                    logger.info("✓ Authenticated state detected - session restored successfully")
                    self.is_connected = True
                    # Save session to ensure it's up to date
                    try:
                        await self._save_session()
                        logger.info("✓ Session saved after restoration")
                    except Exception as e:
                        logger.error(f"Error saving session after restoration: {e}")
                    logger.info("WhatsApp service initialized - session restored successfully")
                    return  # Exit early - we're authenticated
                except Exception as e:
                    logger.warning(f"Timeout waiting for authenticated state (this is normal if page is still loading): {e}")
                    # Even if wait_for_function timed out, check if we're actually authenticated
                    # Sometimes the page loads but the function check is too strict
                    quick_check = await self.page.evaluate("""
                        () => {
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            const hasChats = document.querySelectorAll('div[data-testid="chat"]').length > 0;
                            const hasChatlist = !!document.querySelector('div[data-testid="chatlist"]');
                            return !hasQR && (hasChats || hasChatlist);
                        }
                    """)
                    if quick_check:
                        logger.info("✓ Authentication detected on quick check after timeout")
                        self.is_connected = True
                        try:
                            await self._save_session()
                            logger.info("✓ Session saved after restoration")
                        except Exception as e:
                            logger.error(f"Error saving session: {e}")
                        logger.info("WhatsApp service initialized - session restored successfully")
                        return  # Exit early - we're authenticated
                    # Continue to check authentication status with the regular method
            
            # Check authentication status (for cases where wait_for_selector didn't catch it)
            is_authenticated = await self._check_authentication_status()
            
            if not is_authenticated:
                if not self.has_session:
                    # No session and not authenticated
                    logger.info("No session found - authentication required")
                    # Start monitoring for authentication
                    asyncio.create_task(self._monitor_authentication())
                else:
                    # We have a session but authentication check failed
                    # Session restoration might take time - wait and check multiple times
                    logger.info("Session exists but not authenticated yet. Waiting for session to restore...")
                    
                    # Wait longer and check multiple times for session restoration
                    # WhatsApp Web session restoration can be slow - be very patient
                    max_wait_attempts = 60  # Increased to 60 seconds - session restoration needs time
                    logger.info(f"Waiting up to {max_wait_attempts} seconds for session restoration...")
                    logger.info("Please be patient - WhatsApp Web is validating and restoring your session...")
                    for attempt in range(max_wait_attempts):
                        await asyncio.sleep(1)
                        if attempt % 5 == 0:  # Log every 5 seconds
                            logger.info(f"Session restoration check attempt {attempt + 1}/{max_wait_attempts}...")
                        is_authenticated = await self._check_authentication_status()
                        
                        if is_authenticated:
                            logger.info(f"✓ Session restored successfully after {attempt + 1} seconds")
                            self.is_connected = True  # Make sure this is set!
                            # Save session to ensure it's up to date
                            try:
                                await self._save_session()
                                logger.info("✓ Session saved after restoration")
                            except Exception as e:
                                logger.error(f"Error saving session after restoration: {e}")
                            break
                        
                        # Check if QR code is visible (session expired) - but only after waiting long enough
                        # Don't mark as expired too quickly - WhatsApp Web may show QR temporarily during loading
                        if attempt >= 20:  # Only check after 20 seconds of waiting
                            if attempt % 5 == 0:  # Check every 5 seconds after 20 seconds
                                try:
                                    qr_visible = await self.page.evaluate("""
                                        () => {
                                            const qr = document.querySelector('div[data-ref]');
                                            return qr && qr.offsetParent !== null;
                                        }
                                    """)
                                    # Also check if we have authenticated content
                                    has_auth_content = await self.page.evaluate("""
                                        () => {
                                            return document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                                   !!document.querySelector('div[data-testid="chatlist"]');
                                        }
                                    """)
                                    # Only mark as expired if QR is visible AND we don't have auth content
                                    if qr_visible and not has_auth_content:
                                        logger.warning(f"QR code visible and no auth content after {attempt + 1} seconds - session may be expired")
                                        self.has_session = False  # Mark session as invalid
                                        asyncio.create_task(self._monitor_authentication())
                                        break
                                except Exception as e:
                                    logger.debug(f"Error checking QR visibility: {e}")
                    
                    # Final check - only mark as expired if we're absolutely sure
                    if not is_authenticated:
                        # Check one more time after waiting longer
                        await asyncio.sleep(5)
                        is_authenticated = await self._check_authentication_status()
                        
                        # Double-check: QR visible AND no auth content means expired
                        if not is_authenticated:
                            try:
                                qr_check = await self.page.evaluate("""
                                    () => {
                                        const qr = document.querySelector('div[data-ref]');
                                        const hasQR = qr && qr.offsetParent !== null;
                                        const hasAuthContent = document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                                              !!document.querySelector('div[data-testid="chatlist"]');
                                        return {hasQR: hasQR, hasAuthContent: hasAuthContent};
                                    }
                                """)
                                # Only mark as expired if QR is clearly visible and no auth content
                                if qr_check.get('hasQR') and not qr_check.get('hasAuthContent'):
                                    logger.warning("Session exists but authentication did not restore after waiting. Session appears expired.")
                                    self.has_session = False  # Mark session as invalid
                                    asyncio.create_task(self._monitor_authentication())
                                else:
                                    # Still loading, don't mark as expired yet
                                    logger.info("Session restoration still in progress - QR code not definitively visible or auth content loading")
                            except Exception as e:
                                logger.warning(f"Error in final session check: {e}, keeping session")
                    elif is_authenticated:
                        logger.info("✓ Session restored - authentication successful")
                        self.is_connected = True  # Make sure this is set!
                        # Save session to ensure it's up to date
                        try:
                            await self._save_session()
                            logger.info("✓ Session saved after restoration")
                        except Exception as e:
                            logger.error(f"Error saving session after restoration: {e}")
            else:
                logger.info("✓ Successfully authenticated with existing session")
                self.is_connected = True  # Make sure this is set!
                # Save session to ensure it's up to date
                try:
                    await self._save_session()
                    logger.info("✓ Session saved after authentication check")
                except Exception as e:
                    logger.error(f"Error saving session: {e}")
            
            logger.info("WhatsApp service initialized")
                
        except Exception as e:
            logger.error(f"Error initializing WhatsApp service: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self._initializing = False
    
    async def _check_authentication_status(self):
        """Check if user is authenticated"""
        try:
            # Fast path: if already connected, return immediately
            if self.is_connected:
                return True
                
            if not self.page:
                return False
            
            # Wait longer if we have a session (page might still be loading)
            if self.has_session:
                await asyncio.sleep(3.0)  # Increased wait for session restoration
                logger.debug("Waiting longer for session restoration in auth check")
            else:
                await asyncio.sleep(0.3)
            
            # Check current URL
            current_url = self.page.url
            logger.debug(f"Checking authentication - Current URL: {current_url}")
            
            # Use JavaScript to check for authentication indicators
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
                            if (elem && elem.offsetParent !== null) {
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                # Check for authenticated state indicators
                auth_indicators = await self.page.evaluate("""
                    () => {
                        const results = {};
                        
                        // Check for chat list
                        results.chatlist = !!document.querySelector('div[data-testid="chatlist"]');
                        
                        // Check for sidebar
                        results.sidebar = !!document.querySelector('div[data-testid="sidebar"]');
                        
                        // Check for chat items (most reliable indicator)
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
                            results.hasQRInApp = !!hasQR && hasQR.offsetParent !== null; // Check if visible
                            if (!results.hasQRInApp) {
                                const hasContent = app.querySelector('div[class*="chat"], div[class*="panel"], div[class*="pane"]');
                                results.hasContent = !!hasContent;
                            }
                        }
                        
                        // Check for WhatsApp Web main interface elements
                        results.hasMainInterface = !!document.querySelector('div[data-testid="conversation-panel-wrapper"]') ||
                                                   !!document.querySelector('div[data-testid="chatlist"]') ||
                                                   !!document.querySelector('div[role="grid"]');
                        
                        // Check URL - if we're on the main WhatsApp Web page (not login), we're likely authenticated
                        const url = window.location.href;
                        results.onMainPage = url.includes('web.whatsapp.com') && !url.includes('login');
                        
                        // Check for loading indicators
                        const loadingSpinner = document.querySelector('div[data-testid="loading"]') || 
                                               document.querySelector('div[class*="loading"]') ||
                                               document.querySelector('div[class*="spinner"]');
                        results.isLoading = !!loadingSpinner && loadingSpinner.offsetParent !== null;
                        
                        // Check if page has any meaningful content (even if not fully loaded)
                        const hasAnyDivs = document.querySelectorAll('div').length > 10; // WhatsApp has many divs
                        results.hasPageContent = hasAnyDivs;
                        
                        // More comprehensive authentication check
                        // If we have ANY of these AND no visible QR code, we're authenticated
                        const hasAnyAuthIndicator = (
                            results.chatlist || 
                            results.sidebar ||
                            results.chatCount > 0 ||
                            results.search ||
                            results.listItemCount > 0 ||
                            results.hasMainInterface
                        );
                        
                        // If we're on the main page, no QR code, and have page content, we're likely authenticated
                        // (even if auth indicators aren't fully loaded yet)
                        const isLikelyAuthenticated = (
                            results.onMainPage && 
                            !results.hasQRInApp && 
                            results.hasPageContent &&
                            !results.isLoading
                        );
                        
                        const isAuthenticated = hasAnyAuthIndicator && !results.hasQRInApp;
                        
                        return {
                            authenticated: isAuthenticated || isLikelyAuthenticated,
                            indicators: results,
                            summary: (isAuthenticated || isLikelyAuthenticated) ? 'AUTHENTICATED' : 'NOT_AUTHENTICATED',
                            isLikelyAuthenticated: isLikelyAuthenticated
                        };
                    }
                """)
                
                logger.info(f"QR code exists: {qr_exists}, Auth check: {auth_indicators.get('summary', 'UNKNOWN')}")
                logger.info(f"Auth indicators: {auth_indicators.get('indicators', {})}")
                logger.info(f"Is likely authenticated: {auth_indicators.get('isLikelyAuthenticated', False)}")
                
                # If we have auth indicators and no QR code, we're authenticated
                if auth_indicators.get('authenticated') and not qr_exists:
                    if not self.is_connected:
                        logger.info(f"✓ Authentication detected via JavaScript: {auth_indicators.get('indicators', {})}")
                    self.is_connected = True
                    # Save session immediately when authentication is detected
                    try:
                        await self._save_session()
                        logger.info("✓ Session saved after authentication")
                    except Exception as e:
                        logger.error(f"Error saving session: {e}")
                    return True
                elif qr_exists:
                    # QR code is visible - this means session is expired or invalid
                    # If we had a session but QR code is showing, the session expired
                    if self.has_session:
                        logger.warning("⚠ QR code visible despite having session - session is EXPIRED or INVALID")
                        logger.warning("⚠ Session file exists but credentials are no longer valid")
                        logger.warning("⚠ Clearing invalid session - user needs to re-authenticate")
                        # Mark session as invalid
                        self.has_session = False
                        # Optionally delete the invalid session file
                        try:
                            storage_state_path = os.path.join(self.session_path, 'storage_state.json')
                            if os.path.exists(storage_state_path):
                                # Backup the invalid session before deleting (for debugging)
                                backup_path = storage_state_path + '.expired'
                                import shutil
                                shutil.move(storage_state_path, backup_path)
                                logger.info(f"Invalid session file moved to {backup_path}")
                        except Exception as e:
                            logger.warning(f"Error handling invalid session file: {e}")
                    self.is_connected = False
                    logger.debug("QR code visible - not authenticated")
                    return False
                elif auth_indicators.get('isLikelyAuthenticated'):
                    # We're on the main page, no QR code, and have content - likely authenticated
                    # Wait a bit more and check again to be sure
                    logger.info("Likely authenticated - waiting a moment to confirm...")
                    await asyncio.sleep(2.0)  # Wait longer
                    # Check one more time with more comprehensive checks
                    final_check = await self.page.evaluate("""
                        () => {
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            
                            // Multiple checks for authenticated state
                            const hasChatlist = !!document.querySelector('div[data-testid="chatlist"]');
                            const hasChats = document.querySelectorAll('div[data-testid="chat"]').length > 0;
                            const hasSidebar = !!document.querySelector('div[data-testid="sidebar"]');
                            const hasSearch = !!document.querySelector('div[data-testid="chat-list-search"]');
                            const hasListItems = document.querySelectorAll('div[role="listitem"]').length > 0;
                            
                            // Check if we're on the main WhatsApp page (not login page)
                            const url = window.location.href;
                            const onMainPage = url.includes('web.whatsapp.com') && !url.includes('login');
                            
                            // If no QR code and we have any of these indicators, we're authenticated
                            const isAuth = !hasQR && (
                                hasChatlist || 
                                hasChats || 
                                hasSidebar || 
                                hasSearch || 
                                hasListItems ||
                                (onMainPage && document.querySelectorAll('div').length > 50) // Has substantial content
                            );
                            
                            return {
                                authenticated: isAuth,
                                hasQR: hasQR,
                                indicators: {
                                    chatlist: hasChatlist,
                                    chats: hasChats,
                                    sidebar: hasSidebar,
                                    search: hasSearch,
                                    listItems: hasListItems,
                                    onMainPage: onMainPage,
                                    divCount: document.querySelectorAll('div').length
                                }
                            };
                        }
                    """)
                    
                    if final_check.get('authenticated'):
                        logger.info(f"✓ Authentication confirmed - page loaded successfully. Indicators: {final_check.get('indicators', {})}")
                        self.is_connected = True
                        try:
                            await self._save_session()
                            logger.info("✓ Session saved after authentication")
                        except Exception as e:
                            logger.error(f"Error saving session: {e}")
                        return True
                    else:
                        logger.warning(f"Initial check suggested authentication but final check failed. Final check result: {final_check}")
                        # If we have a session and no QR code, we might still be loading
                        # If we have a session and no QR code is visible, we're likely authenticated
                        # (even if specific indicators aren't showing yet - session restoration can be slow)
                        if self.has_session and not final_check.get('hasQR'):
                            logger.info("Session exists and no QR code visible - likely authenticated (page may still be loading)")
                            # Give it a bit more time and check one more time
                            await asyncio.sleep(2)
                            final_retry = await self.page.evaluate("""
                                () => {
                                    const qr = document.querySelector('div[data-ref]');
                                    const hasQR = qr && qr.offsetParent !== null;
                                    const hasAnyContent = document.querySelectorAll('div[data-testid="chat"], div[data-testid="chatlist"], div[data-testid="sidebar"]').length > 0;
                                    return !hasQR && (hasAnyContent || document.querySelectorAll('div').length > 50);
                                }
                            """)
                            if final_retry:
                                logger.info("✓ Authentication confirmed on final retry with session")
                                self.is_connected = True
                                try:
                                    await self._save_session()
                                    logger.info("✓ Session saved after authentication")
                                except Exception as e:
                                    logger.error(f"Error saving session: {e}")
                                return True
                            logger.info("Session exists but page still loading - will check again later")
                        self.is_connected = False
                        return False
                else:
                    # No QR code but also no clear auth indicators - might be in transition
                    # Check more carefully
                    has_any_content = (
                        auth_indicators.get('indicators', {}).get('chatCount', 0) > 0 or
                        auth_indicators.get('indicators', {}).get('listItemCount', 0) > 0 or
                        auth_indicators.get('indicators', {}).get('hasContent', False)
                    )
                    if has_any_content:
                        logger.info("✓ Authentication detected - content found on page")
                        self.is_connected = True
                        try:
                            await self._save_session()
                            logger.info("✓ Session saved after authentication")
                        except Exception as e:
                            logger.error(f"Error saving session: {e}")
                        return True
                    else:
                        # If we have a session but no indicators yet, might still be loading
                        if self.has_session:
                            logger.info("Session exists but page might still be loading - checking one more time with longer wait...")
                            # One more check after waiting longer
                            await asyncio.sleep(3)  # Increased from 2 to 3 seconds
                            final_auth_check = await self.page.evaluate("""
                                () => {
                                    const qr = document.querySelector('div[data-ref]');
                                    const hasQR = qr && qr.offsetParent !== null;
                                    if (hasQR) return false;
                                    
                                    // Check for any authenticated content
                                    const hasAnyContent = (
                                        !!document.querySelector('div[data-testid="chatlist"]') ||
                                        document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                        !!document.querySelector('div[data-testid="sidebar"]') ||
                                        document.querySelectorAll('div[role="listitem"]').length > 0 ||
                                        document.querySelectorAll('div').length > 50
                                    );
                                    
                                    const url = window.location.href;
                                    const onMainPage = url.includes('web.whatsapp.com') && !url.includes('login');
                                    
                                    return !hasQR && onMainPage && hasAnyContent;
                                }
                            """)
                            
                            if final_auth_check:
                                logger.info("✓ Authentication detected on final check")
                                self.is_connected = True
                                try:
                                    await self._save_session()
                                    logger.info("✓ Session saved after authentication")
                                except Exception as e:
                                    logger.error(f"Error saving session: {e}")
                                return True
                            else:
                                logger.warning("Session exists but authentication not detected after multiple checks")
                        self.is_connected = False
                        return False
                    
            except Exception as e:
                logger.warning(f"Error checking authentication status: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Error in authentication check: {e}")
            return False
    
    async def _save_session(self):
        """Save browser context state for session persistence"""
        try:
            if not self.context:
                logger.warning("Cannot save session: browser context does not exist")
                return
            
            if not self.is_connected:
                logger.debug("Not saving session: not connected yet")
                return
            
            storage_state = await self.context.storage_state()
            storage_state_path = os.path.join(self.session_path, 'storage_state.json')
            
            # Ensure directory exists
            os.makedirs(self.session_path, exist_ok=True)
            
            # Remove expired session file if it exists (cleanup)
            expired_path = storage_state_path + '.expired'
            if os.path.exists(expired_path):
                try:
                    os.remove(expired_path)
                    logger.debug(f"Removed expired session file: {expired_path}")
                except Exception as e:
                    logger.debug(f"Could not remove expired session file: {e}")
            
            # Save session to file with atomic write (write to temp file first, then rename)
            # This ensures the file is either fully written or doesn't exist (no partial writes)
            temp_path = storage_state_path + '.tmp'
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(storage_state, f, indent=2)
                
                # Atomically replace the old file with the new one
                if os.path.exists(storage_state_path):
                    os.replace(temp_path, storage_state_path)
                else:
                    os.rename(temp_path, storage_state_path)
                
                logger.info(f"✓ WhatsApp session saved successfully to {storage_state_path}")
                
                # Wait a moment to ensure file is fully written to disk
                await asyncio.sleep(0.2)
                
                # Verify the saved file exists and is valid
                if os.path.exists(storage_state_path):
                    file_size = os.path.getsize(storage_state_path)
                    logger.info(f"Session file exists with size: {file_size} bytes")
                    
                    # Update has_session flag and verify the session file has valid data
                    self.has_session = self._check_session_exists()
                    
                    if self.has_session:
                        logger.info("✓✓✓ Session file verified and marked as existing - auto-connect will work on next restart ✓✓✓")
                        # Log detailed session info for debugging
                        try:
                            with open(storage_state_path, 'r', encoding='utf-8') as f:
                                saved_data = json.load(f)
                                origins_count = len(saved_data.get('origins', []))
                                cookies_count = len(saved_data.get('cookies', []))
                                whatsapp_cookies = [c for c in saved_data.get('cookies', []) if 'whatsapp.com' in c.get('domain', '').lower()]
                                logger.info(f"Session file details: {origins_count} origins, {cookies_count} total cookies ({len(whatsapp_cookies)} WhatsApp cookies)")
                        except Exception as e:
                            logger.debug(f"Could not read saved session file for debugging: {e}")
                    else:
                        logger.warning("⚠⚠⚠ Session file saved but verification failed - session might not work on restart ⚠⚠⚠")
                        # Try to read the file and log its contents for debugging
                        try:
                            with open(storage_state_path, 'r', encoding='utf-8') as f:
                                saved_data = json.load(f)
                                origins_count = len(saved_data.get('origins', []))
                                cookies_count = len(saved_data.get('cookies', []))
                                logger.warning(f"Session file stats (verification failed): {origins_count} origins, {cookies_count} cookies")
                                logger.warning("This might indicate the session data format is incorrect or incomplete")
                        except Exception as e:
                            logger.warning(f"Could not read saved session file for debugging: {e}")
                else:
                    logger.error(f"⚠⚠⚠ CRITICAL: Session file was NOT created at {storage_state_path} ⚠⚠⚠")
            except Exception as e:
                logger.error(f"Error during atomic file write: {e}")
                # Try to clean up temp file if it exists
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                raise
                    
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _monitor_authentication(self):
        """Monitor for authentication completion"""
        max_attempts = 300  # 5 minutes
        attempts = 0
        
        while attempts < max_attempts and not self.is_connected:
            attempts += 1
            await asyncio.sleep(1)
            
            try:
                is_authenticated = await self._check_authentication_status()
                
                if is_authenticated:
                    logger.info("✓ Authentication detected during monitoring!")
                    self.is_connected = True
                    # Explicitly save session when authentication is detected - CRITICAL for persistence
                    try:
                        await self._save_session()
                        # Wait a moment to ensure file is fully written
                        await asyncio.sleep(0.5)
                        
                        # Verify session file exists
                        storage_state_path = os.path.join(self.session_path, 'storage_state.json')
                        if os.path.exists(storage_state_path):
                            logger.info("✓ Session file exists after save")
                            # Re-check session to update has_session flag
                            self.has_session = self._check_session_exists()
                            if self.has_session:
                                logger.info("✓ Session verified - auto-reconnect will work on next app restart")
                            else:
                                logger.warning("Session file exists but verification failed - may need to re-authenticate on restart")
                        else:
                            logger.error(f"Session file was not created at {storage_state_path} - auto-reconnect will not work")
                        
                        logger.info("✓ Session saved after authentication detection")
                    except Exception as e:
                        logger.error(f"Error saving session after authentication: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                    break
                    
            except Exception as e:
                logger.warning(f"Error in authentication monitoring: {e}")
                continue
        
        if attempts >= max_attempts and not self.is_connected:
            logger.warning("Authentication monitoring stopped (timeout after 5 minutes)")
        elif self.is_connected:
            logger.info("✓ Authentication monitoring completed successfully")
    
    async def _ensure_page_ready(self):
        """
        Ensure the page is on WhatsApp Web and ready for operations
        """
        if not self.page:
            raise Exception("WhatsApp page not initialized")
        
        try:
            current_url = self.page.url
            if 'web.whatsapp.com' not in current_url:
                logger.info("Navigating to WhatsApp Web...")
                await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)
            
            # Ensure we're authenticated before proceeding
            if not self.is_connected:
                logger.info("Not connected - checking connection status...")
                is_connected, msg = await self.check_connection_status()
                if not is_connected:
                    raise Exception(f"Not connected to WhatsApp: {msg}")
                # Connection status check should have set is_connected, but verify
                if not self.is_connected:
                    # Do one more authentication check
                    is_authenticated = await self._check_authentication_status()
                    if not is_authenticated:
                        raise Exception("Not authenticated. Please authenticate to connect.")
                    self.is_connected = True
            
            # Wait for page to be interactive
            try:
                await self.page.wait_for_load_state('networkidle', timeout=15000)
            except Exception as e:
                logger.warning(f"Timeout waiting for networkidle: {e}, continuing anyway...")
            
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error ensuring page is ready: {e}")
            raise
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check WhatsApp connection status
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        if not PLAYWRIGHT_AVAILABLE:
            return False, "Playwright not installed. Install with: pip install playwright && playwright install chromium"
        
        # If initialization is in progress, wait for it to complete (with timeout)
        if self._initializing:
            logger.info("Initialization in progress - waiting for it to complete...")
            max_wait = 120  # Wait up to 2 minutes
            waited = 0
            while self._initializing and waited < max_wait:
                await asyncio.sleep(1)
                waited += 1
            if waited >= max_wait:
                logger.warning("Timeout waiting for initialization to complete")
        
        if not self.page:
            # Try to initialize
            try:
                await self.initialize()
            except Exception as e:
                logger.error(f"Error initializing WhatsApp: {e}")
                return False, f"Error initializing: {str(e)}"
        
        # If we think we're connected, verify the page is still on WhatsApp Web and authenticated
        if self.is_connected:
            try:
                current_url = self.page.url
                if 'web.whatsapp.com' not in current_url:
                    logger.warning("Page navigated away from WhatsApp Web - reconnecting...")
                    await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(2)
                    # Re-check authentication
                    is_authenticated = await self._check_authentication_status()
                    if not is_authenticated:
                        self.is_connected = False
                        return False, "Lost connection to WhatsApp. Please re-authenticate."
                else:
                    # Verify we're still authenticated (quick check)
                    try:
                        has_chats = await self.page.evaluate("""() => document.querySelectorAll('div[data-testid="chat"]').length > 0""")
                        if not has_chats:
                            # Do a full authentication check
                            is_authenticated = await self._check_authentication_status()
                            if not is_authenticated:
                                self.is_connected = False
                                return False, "Authentication lost. Please re-authenticate."
                    except Exception:
                        # If evaluation fails, do a full check
                        is_authenticated = await self._check_authentication_status()
                        if not is_authenticated:
                            self.is_connected = False
                            return False, "Connection verification failed. Please re-authenticate."
                
                return True, "Connected to WhatsApp"
            except Exception as e:
                logger.error(f"Error verifying connection: {e}")
                self.is_connected = False
                return False, f"Connection error: {str(e)}"
        
        # Check current status
        try:
            # If we have a session but not connected, this is critical - we need to wait for session restoration
            if self.has_session and not self.is_connected:
                logger.info("Session exists but not connected - waiting for session restoration...")
                
                # Ensure we're on WhatsApp Web
                try:
                    current_url = self.page.url
                    if 'web.whatsapp.com' not in current_url:
                        logger.info("Not on WhatsApp Web - navigating...")
                        await self.page.goto('https://web.whatsapp.com', wait_until='networkidle', timeout=30000)
                        await asyncio.sleep(3)
                except Exception as nav_error:
                    logger.warning(f"Error navigating: {nav_error}")
                
                # Wait for authenticated state to appear (same logic as in initialize)
                logger.info("Waiting for authenticated state to appear (session restoration)...")
                try:
                    # Use wait_for_function to wait for authenticated indicators
                    await self.page.wait_for_function("""
                        () => {
                            // Check for any authenticated state indicators
                            const hasChatlist = !!document.querySelector('div[data-testid="chatlist"]');
                            const hasChats = document.querySelectorAll('div[data-testid="chat"]').length > 0;
                            const hasSidebar = !!document.querySelector('div[data-testid="sidebar"]');
                            const hasSearch = !!document.querySelector('div[data-testid="chat-list-search"]');
                            const hasListItems = document.querySelectorAll('div[role="listitem"]').length > 0;
                            
                            // Check if QR code is NOT visible
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            
                            // We're authenticated if we have any auth indicators AND no QR code
                            return (hasChatlist || hasChats || hasSidebar || hasSearch || hasListItems) && !hasQR;
                        }
                    """, timeout=30000)
                    logger.info("✓ Authenticated state detected - session restored successfully")
                    self.is_connected = True
                    # Save session to ensure it's up to date
                    try:
                        await self._save_session()
                        logger.info("✓ Session saved after restoration in check_connection_status")
                    except Exception as e:
                        logger.error(f"Error saving session: {e}")
                    return True, "Connected to WhatsApp (session restored)"
                except Exception as wait_error:
                    logger.warning(f"Timeout waiting for authenticated state: {wait_error}")
                    # Check if QR code appeared (session expired) - but be more careful
                    qr_check = await self.page.evaluate("""
                        () => {
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            const hasAuthContent = document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                                  !!document.querySelector('div[data-testid="chatlist"]');
                            return {hasQR: hasQR, hasAuthContent: hasAuthContent};
                        }
                    """)
                    # Only mark as expired if QR is visible AND no auth content
                    if qr_check.get('hasQR') and not qr_check.get('hasAuthContent'):
                        logger.warning("⚠ QR code detected and no auth content after timeout - session may be expired")
                        # Session is expired - mark as invalid so QR code will be shown
                        self.has_session = False
                        # Delete the invalid session file
                        try:
                            storage_state_path = os.path.join(self.session_path, 'storage_state.json')
                            if os.path.exists(storage_state_path):
                                backup_path = storage_state_path + '.expired'
                                import shutil
                                shutil.move(storage_state_path, backup_path)
                                logger.info(f"Expired session file moved to {backup_path}")
                        except Exception as e:
                            logger.warning(f"Error handling expired session file: {e}")
                    else:
                        logger.info("QR code check: QR may be visible but auth content also present, or still loading - keeping session")
                    # Continue to regular authentication check
            
            # Always check authentication status - this is the key check
            is_authenticated = await self._check_authentication_status()
            
            # If we have a session but still not authenticated, wait a bit more and check again
            if self.has_session and not is_authenticated and not self.is_connected:
                logger.info("Session exists but not authenticated yet - waiting a bit more and rechecking...")
                await asyncio.sleep(5)  # Increased wait time
                is_authenticated = await self._check_authentication_status()
                
                # If still not authenticated, try one more time with even longer wait
                if not is_authenticated and not self.is_connected:
                    logger.info("Still not authenticated - waiting longer for session to fully restore...")
                    await asyncio.sleep(5)  # Increased wait time
                    is_authenticated = await self._check_authentication_status()
            
            if is_authenticated:
                if not self.is_connected:
                    logger.info("✓ User authenticated - establishing connection")
                    self.is_connected = True
                    # Save session to ensure it persists
                    try:
                        await self._save_session()
                        logger.info("✓ Session saved in check_connection_status")
                    except Exception as e:
                        logger.error(f"Error saving session: {e}")
                return True, "Connected to WhatsApp"
            elif not self.is_connected:
                # Check if QR code is visible - if so, session is expired
                try:
                    qr_check = await self.page.evaluate("""
                        () => {
                            const qr = document.querySelector('div[data-ref]');
                            const hasQR = qr && qr.offsetParent !== null;
                            const hasAuthContent = document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                                  !!document.querySelector('div[data-testid="chatlist"]');
                            return {hasQR: hasQR, hasAuthContent: hasAuthContent};
                        }
                    """)
                    qr_visible = qr_check.get('hasQR', False)
                    has_auth_content = qr_check.get('hasAuthContent', False)
                    
                    # Only treat as expired if QR is visible AND no auth content
                    if qr_visible and not has_auth_content:
                        if self.has_session:
                            logger.warning("⚠ QR code visible and no auth content - session is EXPIRED")
                            logger.warning("⚠ Session file will be marked as invalid - user needs to re-authenticate")
                            self.has_session = False
                            # Move expired session file
                            try:
                                storage_state_path = os.path.join(self.session_path, 'storage_state.json')
                                if os.path.exists(storage_state_path):
                                    backup_path = storage_state_path + '.expired'
                                    import shutil
                                    shutil.move(storage_state_path, backup_path)
                                    logger.info(f"Expired session file moved to {backup_path}")
                            except Exception as e:
                                logger.warning(f"Error handling expired session file: {e}")
                        # Session expired - start monitoring for authentication
                        asyncio.create_task(self._monitor_authentication())
                    elif qr_visible and has_auth_content:
                        # QR might be visible but we also have auth content - session is restoring
                        logger.info("QR code visible but auth content also present - session is restoring, keeping session")
                    elif not self.has_session:
                        logger.info("No session available - authentication required")
                        asyncio.create_task(self._monitor_authentication())
                except Exception as e:
                    logger.warning(f"Error checking QR code visibility: {e}")
        except Exception as e:
            logger.error(f"Error checking status: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        if self.is_connected:
            return True, "Connected to WhatsApp"
        else:
            return False, "Not connected. Please authenticate to connect."
    
    async def get_contacts(self) -> List[WhatsAppContact]:
        """
        Retrieve all WhatsApp contacts/chats
        
        Returns:
            List of WhatsApp contacts
        """
        if not self.page:
            # Try to initialize if page doesn't exist
            try:
                await self.initialize()
            except Exception as e:
                raise Exception(f"Failed to initialize WhatsApp page: {str(e)}")
        
        if not self.is_connected:
            # Try to check connection status first
            logger.info("Not connected - checking connection status...")
            is_connected, msg = await self.check_connection_status()
            if not is_connected:
                raise Exception(f"Not connected to WhatsApp: {msg}. Please authenticate first.")
        
        try:
            # Ensure page is ready and on WhatsApp Web
            logger.info("Ensuring page is ready...")
            await self._ensure_page_ready()
            
            # Wait for chat list to load
            logger.info("Waiting for chat list to appear...")
            chat_list_found = False
            try:
                await self.page.wait_for_selector('div[data-testid="chatlist"]', timeout=10000)
                chat_list_found = True
                logger.info("Chat list container found")
            except Exception as e:
                logger.debug(f"Chat list container not found: {e}")
                # Chat list might not have that exact selector, try waiting for any chat items
                try:
                    await self.page.wait_for_selector('div[data-testid="chat"]', timeout=10000)
                    chat_list_found = True
                    logger.info("Chat items found")
                except Exception as e2:
                    logger.debug(f"Chat items not found: {e2}")
                    # Try waiting for any chat-related element
                    try:
                        await self.page.wait_for_function("""
                            () => {
                                return document.querySelectorAll('div[data-testid="chat"]').length > 0 ||
                                       document.querySelectorAll('div[role="row"]').length > 0 ||
                                       document.querySelector('div[data-testid="chatlist"]') !== null;
                            }
                        """, timeout=10000)
                        chat_list_found = True
                        logger.info("Chat-related elements found")
                    except Exception as e3:
                        logger.warning(f"Could not find chat list after multiple attempts: {e3}")
                        # Continue anyway - might still be able to extract contacts
            
            # Give page a moment to fully render
            await asyncio.sleep(2)  # Increased from 1 to 2 seconds
            
            # Get contacts from the chat list
            logger.info("Extracting contacts from chat list...")
            contacts_data = await self.page.evaluate(r"""
                () => {
                    const contacts = [];
                    // Try multiple selectors for chat items
                    let chatItems = document.querySelectorAll('div[data-testid="chat"]');
                    if (chatItems.length === 0) {
                        // Try alternative selectors
                        chatItems = document.querySelectorAll('div[role="row"]');
                    }
                    if (chatItems.length === 0) {
                        chatItems = document.querySelectorAll('div[class*="chat"]');
                    }
                    
                    chatItems.forEach((item, index) => {
                        if (index >= 100) return; // Limit to 100 contacts
                        
                        try {
                            // Get contact name - try multiple selectors
                            let nameElement = item.querySelector('span[title]');
                            if (!nameElement) {
                                nameElement = item.querySelector('span[data-testid="conversation-info-header"]');
                            }
                            if (!nameElement) {
                                nameElement = item.querySelector('span[class*="title"]');
                            }
                            const name = nameElement ? (nameElement.getAttribute('title') || nameElement.textContent.trim()) : `Contact ${index + 1}`;
                            
                            // Get last message preview
                            let previewElement = item.querySelector('span[class*="text"]');
                            if (!previewElement) {
                                previewElement = item.querySelector('span[class*="preview"]');
                            }
                            const lastMessage = previewElement ? previewElement.textContent.trim() : '';
                            
                            // Try to get phone number from subtitle or other elements
                            let phoneElement = item.querySelector('span[class*="subtitle"]') || 
                                              item.querySelector('span[class*="status"]') ||
                                              item.querySelector('span[class*="phone"]');
                            const phoneText = phoneElement ? phoneElement.textContent.trim() : '';
                            const phoneOnly = phoneText.replace(/[^0-9]/g, '');
                            
                            // Get contact ID - prefer phone number if available, otherwise use normalized name
                            let contactId;
                            if (phoneOnly && phoneOnly.length >= 7) {
                                // Use phone number as contact ID (with underscores for readability)
                                contactId = phoneOnly.replace(/(\d{3})(\d{3})(\d+)/, '$1_$2_$3').replace(/^(\d{1,2})_/, '$1_');
                            } else {
                                // Use normalized name
                                contactId = name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
                            }
                            
                            // Check if it's a group (look for group indicators)
                            const isGroup = item.querySelector('span[data-testid="group"]') !== null || 
                                          item.querySelector('span[title*="group"]') !== null ||
                                          item.querySelector('span[data-testid="group-icon"]') !== null;
                            
                            contacts.push({
                                contact_id: contactId,
                                name: name,
                                is_group: isGroup,
                                last_message: lastMessage,
                                last_message_time: null,
                                unread_count: 0
                            });
                        } catch (e) {
                            console.error('Error parsing contact:', e);
                        }
                    });
                    
                    console.log(`Found ${contacts.length} contacts`);
                    return contacts;
                }
            """)
            
            if not contacts_data or len(contacts_data) == 0:
                logger.warning("No contacts found - chat list might not be loaded yet, retrying...")
                # Try waiting a bit more and retry
                await asyncio.sleep(2)
                contacts_data = await self.page.evaluate(r"""
                    () => {
                        const contacts = [];
                        let chatItems = document.querySelectorAll('div[data-testid="chat"]');
                        if (chatItems.length === 0) {
                            chatItems = document.querySelectorAll('div[role="row"]');
                        }
                        chatItems.forEach((item, index) => {
                            if (index >= 100) return;
                            try {
                                const nameElement = item.querySelector('span[title]');
                                const name = nameElement ? (nameElement.getAttribute('title') || nameElement.textContent.trim()) : `Contact ${index + 1}`;
                                
                                // Try to get phone number
                                let phoneElement = item.querySelector('span[class*="subtitle"]') || 
                                                  item.querySelector('span[class*="status"]');
                                const phoneText = phoneElement ? phoneElement.textContent.trim() : '';
                                const phoneOnly = phoneText.replace(/[^0-9]/g, '');
                                
                                // Get contact ID - prefer phone number if available
                                let contactId;
                                if (phoneOnly && phoneOnly.length >= 7) {
                                    contactId = phoneOnly.replace(/(\d{3})(\d{3})(\d+)/, '$1_$2_$3').replace(/^(\d{1,2})_/, '$1_');
                                } else {
                                    contactId = name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
                                }
                                
                                contacts.push({
                                    contact_id: contactId,
                                    name: name,
                                    is_group: false,
                                    last_message: '',
                                    last_message_time: null,
                                    unread_count: 0
                                });
                            } catch (e) {}
                        });
                        return contacts;
                    }
                """)
            
            contacts = []
            if contacts_data:
                for contact_data in contacts_data:
                    try:
                        # Validate contact data before creating WhatsAppContact
                        if not contact_data.get('name'):
                            logger.warning(f"Skipping contact with no name: {contact_data}")
                            continue
                        contacts.append(WhatsAppContact(**contact_data))
                    except Exception as e:
                        logger.warning(f"Error creating contact object: {e}, data: {contact_data}")
                        continue
            
            if len(contacts) == 0:
                # If no contacts found, check if we're actually authenticated
                logger.warning("No contacts found - checking authentication status...")
                is_authenticated = await self._check_authentication_status()
                if not is_authenticated:
                    raise Exception("Not authenticated. Please authenticate to connect.")
                else:
                    logger.warning("Authenticated but no contacts found - chat list might be empty or still loading")
                    # Return empty list instead of raising error
                    return []
            
            logger.info(f"Successfully retrieved {len(contacts)} contacts")
            return contacts
            
        except Exception as e:
            logger.error(f"Error getting contacts: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise Exception(f"Failed to get contacts: {str(e)}")
    
    async def send_message(
        self,
        contact_id: str,
        text: str
    ) -> str:
        """
        Send a WhatsApp message to a contact
        
        Args:
            contact_id: Contact ID to send the message to
            text: Message text to send
        
        Returns:
            Message ID
        """
        if not self.is_connected:
            # Try to check connection status first
            is_connected, msg = await self.check_connection_status()
            if not is_connected:
                raise Exception(f"Not connected to WhatsApp: {msg}")
        
        if not self.page:
            raise Exception("WhatsApp page not initialized")
        
        try:
            # Ensure page is ready and on WhatsApp Web
            await self._ensure_page_ready()
            
            # Normalize contact_id for matching
            import re
            normalized_contact_id = re.sub(r'[^a-z0-9_]', '', contact_id.lower().replace(' ', '_'))
            
            # Find and click the contact first
            clicked = await self.page.evaluate(f"""
                () => {{
                    const chatItems = document.querySelectorAll('div[data-testid="chat"]');
                    const targetId = '{normalized_contact_id}';
                    
                    for (let item of chatItems) {{
                        const nameElement = item.querySelector('span[title]');
                        if (nameElement) {{
                            const name = nameElement.getAttribute('title') || nameElement.textContent.trim();
                            const contactId = name.toLowerCase().replace(/\\s+/g, '_').replace(/[^a-z0-9_]/g, '');
                            
                            // Try exact match first
                            if (contactId === targetId) {{
                                item.click();
                                return true;
                            }}
                            
                            // Try partial match
                            if (contactId.includes(targetId) || targetId.includes(contactId)) {{
                                item.click();
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}
            """)
            
            if not clicked:
                raise Exception(f"Contact '{contact_id}' not found in chat list. Please make sure the contact exists.")
            
            logger.info(f"Clicked on contact '{contact_id}' - waiting for chat to open...")
            await asyncio.sleep(2)  # Wait for chat to open
            
            # Wait for message input to appear
            try:
                await self.page.wait_for_selector('div[contenteditable="true"][data-testid="conversation-compose-box-input"]', timeout=10000)
                logger.info("Message input found")
            except Exception:
                logger.warning("Message input not found with primary selector, trying alternatives...")
                # Try alternative selectors
                try:
                    await self.page.wait_for_selector('div[contenteditable="true"][data-tab="10"]', timeout=5000)
                except Exception:
                    # Try any contenteditable div
                    await self.page.wait_for_selector('div[contenteditable="true"]', timeout=5000)
            
            # Find the message input box and type the message
            input_found = await self.page.evaluate(f"""
                () => {{
                    // Try multiple selectors for the input box
                    let input = document.querySelector('div[contenteditable="true"][data-testid="conversation-compose-box-input"]');
                    if (!input) {{
                        input = document.querySelector('div[contenteditable="true"][data-tab="10"]');
                    }}
                    if (!input) {{
                        // Try to find any contenteditable div in the compose area
                        const composeArea = document.querySelector('div[data-testid="conversation-compose"]') ||
                                          document.querySelector('footer') ||
                                          document.querySelector('div[class*="compose"]');
                        if (composeArea) {{
                            input = composeArea.querySelector('div[contenteditable="true"]');
                        }}
                    }}
                    if (!input) {{
                        // Last resort: find any contenteditable div
                        input = document.querySelector('div[contenteditable="true"]');
                    }}
                    
                    if (input) {{
                        // Clear any existing text
                        input.textContent = '';
                        // Set the message text
                        input.textContent = `{text}`;
                        // Trigger input event
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        // Also trigger keyup event (WhatsApp sometimes needs this)
                        input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
                        return true;
                    }}
                    return false;
                }}
            """)
            
            if not input_found:
                raise Exception("Could not find message input box. Please make sure a chat is open.")
            
            await asyncio.sleep(0.5)
            
            # Send the message (press Enter or click send button)
            # Try clicking send button first, then fall back to Enter key
            send_button_clicked = await self.page.evaluate("""
                () => {
                    const sendButton = document.querySelector('span[data-testid="send"]') ||
                                     document.querySelector('button[data-testid="send"]') ||
                                     document.querySelector('span[data-icon="send"]');
                    if (sendButton) {
                        sendButton.click();
                        return true;
                    }
                    return false;
                }
            """)
            
            if not send_button_clicked:
                # Fall back to Enter key
                await self.page.keyboard.press('Enter')
                logger.info("Sent message using Enter key")
            else:
                logger.info("Sent message using send button")
            
            await asyncio.sleep(1)
            
            message_id = f"msg_{int(time.time())}"
            logger.info(f"Message sent to {contact_id}: {text[:50]}...")
            return message_id
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise Exception(f"Failed to send message: {str(e)}")
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self.page = None
            logger.info("WhatsApp service cleaned up")
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")

