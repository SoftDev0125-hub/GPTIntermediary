"""
WhatsApp Service
Handles WhatsApp message retrieval using WhatsApp Web via Playwright (headless)
"""

import logging
import os
import asyncio
import base64
import re
from typing import List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

try:
    from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.error("Playwright not installed. Install with: pip install playwright && playwright install chromium")

from models.schemas import WhatsAppMessage

load_dotenv()
logger = logging.getLogger(__name__)


class WhatsAppService:
    """Service for handling WhatsApp operations using WhatsApp Web"""
    
    def __init__(self):
        """Initialize WhatsApp service"""
        load_dotenv(override=True)
        
        # WhatsApp Web configuration
        self.browser = None
        self.page = None
        self.playwright = None
        self.is_connected = False
        
        # Session directory for browser user data
        session_dir = os.path.join(os.path.dirname(__file__), '..', 'whatsapp_session')
        session_dir = os.path.abspath(session_dir)
        os.makedirs(session_dir, exist_ok=True)
        self.session_dir = session_dir
        
        # Browser user data directory
        self.browser_user_data = os.path.join(session_dir, 'browser_user_data')
        self.browser_user_data = os.path.abspath(self.browser_user_data)
        os.makedirs(self.browser_user_data, exist_ok=True)
        
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available. Install with: pip install playwright && playwright install chromium")
        
        logger.info(f"Session directory: {self.session_dir}")
        logger.info(f"Browser user data directory: {self.browser_user_data}")
        logger.info("WhatsApp service initialized")
    
    async def _create_browser(self):
        """Create and configure browser using Playwright (headless)"""
        if not PLAYWRIGHT_AVAILABLE:
            raise Exception("Playwright not installed. Install with: pip install playwright && playwright install chromium")
        
        try:
            self.playwright = await async_playwright().start()
            
            # Use launch_persistent_context for persistent user data (like cookies, sessions)
            context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.browser_user_data,
                headless=True,  # True headless - no browser window
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            
            # Get the first page (or create one if none exists)
            pages = context.pages
            if pages and len(pages) > 0:
                self.page = pages[0]
            else:
                self.page = await context.new_page()
            
            # Store context reference for cleanup
            self.browser = context
            
            logger.info("Playwright browser created successfully (headless)")
            return True
            
        except Exception as e:
            logger.error(f"Error creating Playwright browser: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    async def initialize(self):
        """Initialize WhatsApp Web connection"""
        try:
            if PLAYWRIGHT_AVAILABLE:
                if not self.browser:
                    await self._create_browser()
                
                # Navigate to WhatsApp Web only if not already there
                current_url = self.page.url if self.page else ""
                if 'web.whatsapp.com' not in current_url:
                    logger.info("Navigating to WhatsApp Web with Playwright...")
                    await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1)
                else:
                    logger.info("Already on WhatsApp Web, skipping navigation")
                
                logger.info("WhatsApp Web ready")
            
            # Check connection status
            await self._check_connection_status()
            
        except Exception as e:
            logger.error(f"Error initializing WhatsApp Web: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _check_connection_status(self):
        """Check if WhatsApp Web is connected"""
        try:
            if PLAYWRIGHT_AVAILABLE and self.page:
                # Ensure we're on WhatsApp Web
                try:
                    current_url = self.page.url
                    if 'web.whatsapp.com' not in current_url:
                        await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=10000)
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.debug(f"Error navigating to WhatsApp Web: {str(e)}")
                
                # Quick check - look for main chat interface elements (connected state)
                # Try multiple selectors to find chat list or conversation area
                chat_list_selectors = [
                    '[data-testid="chatlist"]',
                    '[data-testid="conversation-list"]',
                    '#pane-side',
                    '[data-testid="conversation-panel-wrapper"]',
                    '[role="listbox"]',
                ]
                
                for selector in chat_list_selectors:
                    try:
                        chat_list = await self.page.wait_for_selector(selector, timeout=2000)
                        if chat_list:
                            self.is_connected = True
                            logger.info(f"WhatsApp Web is connected - chat list found using: {selector}")
                            return True
                    except PlaywrightTimeout:
                        continue
                
                # Also check for chat items directly
                try:
                    chat_items = await self.page.query_selector_all('[data-testid="cell-frame-container"]')
                    if chat_items and len(chat_items) > 0:
                        self.is_connected = True
                        logger.info(f"WhatsApp Web is connected - found {len(chat_items)} chat items")
                        return True
                except:
                    pass
                
                # Check for main app container (not landing page)
                try:
                    # Check if landing wrapper exists (means not connected)
                    landing_wrapper = await self.page.query_selector('.landing-wrapper, .landing-main')
                    if landing_wrapper:
                        self.is_connected = False
                        logger.info("WhatsApp Web is not connected - landing page found")
                        return False
                    
                    # Check for main app interface
                    main_app = await self.page.query_selector('#app > div:not(.landing-wrapper)')
                    if main_app:
                        # Check if there's a chat list or conversation area
                        chat_area = await self.page.query_selector('[data-testid="chatlist"], #pane-side')
                        if chat_area:
                            self.is_connected = True
                            logger.info("WhatsApp Web is connected - main app interface found")
                            return True
                except Exception as e:
                    logger.debug(f"Error checking app interface: {str(e)}")
                
                # Check for QR code canvas (not connected)
                try:
                    qr_canvas = await self.page.wait_for_selector('canvas', timeout=1000)
                    if qr_canvas:
                        # Verify it's actually visible and has content
                        box = await qr_canvas.bounding_box()
                        if box and box['width'] > 100 and box['height'] > 100:
                            self.is_connected = False
                            logger.info("WhatsApp Web is not connected - QR code canvas found")
                            return False
                except PlaywrightTimeout:
                    pass
                
                # Final check - evaluate page state
                try:
                    page_state = await self.page.evaluate('''() => {
                        // Check for connected indicators
                        const hasChatList = !!document.querySelector('[data-testid="chatlist"], #pane-side');
                        const hasLanding = !!document.querySelector('.landing-wrapper, .landing-main');
                        const hasQR = !!document.querySelector('canvas');
                        
                        if (hasChatList && !hasLanding) return 'connected';
                        if (hasLanding || hasQR) return 'not_connected';
                        return 'unknown';
                    }''')
                    
                    if page_state == 'connected':
                        self.is_connected = True
                        logger.info("WhatsApp Web is connected - page state check")
                        return True
                    elif page_state == 'not_connected':
                        self.is_connected = False
                        logger.info("WhatsApp Web is not connected - page state check")
                        return False
                except Exception as e:
                    logger.debug(f"Error evaluating page state: {str(e)}")
                
                self.is_connected = False
                return False
            else:
                self.is_connected = False
                return False
                    
        except Exception as e:
            logger.error(f"Error checking connection status: {str(e)}")
            self.is_connected = False
            return False
    
    async def get_qr_code(self) -> Optional[str]:
        """Get QR code for WhatsApp Web authentication"""
        try:
            # Ensure browser/page is initialized
            if PLAYWRIGHT_AVAILABLE:
                if not self.browser or not self.page:
                    logger.info("Browser not initialized, creating browser...")
                    await self._create_browser()
            
            # Check connection status first (quick check)
            is_connected = await self._check_connection_status()
            if is_connected:
                logger.info("Already connected, no QR code needed")
                return None
            
            logger.info("Not connected, attempting to extract QR code...")
            
            # Use Playwright if available
            if PLAYWRIGHT_AVAILABLE and self.page:
                try:
                    logger.info("Extracting QR code using Playwright...")
                    
                    # Navigate to WhatsApp Web if not already there
                    current_url = self.page.url if self.page else ""
                    if 'web.whatsapp.com' not in current_url:
                        logger.info("Navigating to WhatsApp Web...")
                        await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1)
                    else:
                        # Just reload to get fresh QR code (faster than full reload)
                        logger.info("Reloading page to get fresh QR code...")
                        try:
                            await self.page.reload(wait_until="domcontentloaded", timeout=10000)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            logger.debug(f"Reload failed, trying fresh navigation: {str(e)}")
                            await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(1)
                    
                    # Wait for QR code canvas to appear
                    qr_element = None
                    try:
                        # Wait for canvas element or landing wrapper
                        await self.page.wait_for_selector('canvas, .landing-wrapper, [data-ref]', timeout=5000)
                        await asyncio.sleep(1)  # Wait for QR code to render
                        
                        # Try multiple selectors to find the QR code canvas
                        canvas_selectors = [
                            'canvas',
                            'canvas[aria-label*="QR"]',
                            'canvas[aria-label*="code"]',
                            '#app canvas',
                            '.landing-wrapper canvas',
                            '[data-ref] canvas',
                        ]
                        
                        for selector in canvas_selectors:
                            try:
                                elements = await self.page.query_selector_all(selector)
                                for elem in elements:
                                    # Check if element is visible and has reasonable size
                                    box = await elem.bounding_box()
                                    if box and box['width'] > 200 and box['height'] > 200:
                                        qr_element = elem
                                        logger.info(f"Found QR code canvas with selector: {selector} ({box['width']}x{box['height']})")
                                        break
                                if qr_element:
                                    break
                            except Exception as e:
                                logger.debug(f"Selector {selector} failed: {str(e)}")
                                continue
                        
                        # If not found by selectors, get the largest canvas
                        if not qr_element:
                            all_canvases = await self.page.query_selector_all('canvas')
                            largest_canvas = None
                            largest_size = 0
                            for canvas in all_canvases:
                                try:
                                    box = await canvas.bounding_box()
                                    if box:
                                        size = box['width'] * box['height']
                                        if size > largest_size and box['width'] > 200 and box['height'] > 200:
                                            largest_size = size
                                            largest_canvas = canvas
                                except:
                                    continue
                            if largest_canvas:
                                qr_element = largest_canvas
                                logger.info("Using largest canvas as QR code")
                        
                    except PlaywrightTimeout:
                        logger.warning("QR code canvas not found, trying full page screenshot...")
                    
                    # Take screenshot of ONLY the QR code element (not the full page)
                    screenshot_path = os.path.join(self.session_dir, 'qr_screenshot.png')
                    
                    if qr_element:
                        # Get the exact bounding box of the QR code
                        box = await qr_element.bounding_box()
                        if box:
                            # Screenshot ONLY the QR code element with high quality
                            # This ensures we capture only the canvas, not the entire page
                            await qr_element.screenshot(
                                path=screenshot_path,
                                scale='device',  # Use device pixel ratio for better quality
                                type='png'
                            )
                            logger.info(f"QR code element screenshot saved to: {screenshot_path} (size: {box['width']}x{box['height']})")
                            
                            # Verify the screenshot is reasonable size (QR codes are typically 200-400px)
                            if os.path.exists(screenshot_path):
                                file_size = os.path.getsize(screenshot_path)
                                logger.info(f"QR code screenshot file size: {file_size} bytes")
                        else:
                            # If bounding box not available, try direct screenshot
                            await qr_element.screenshot(path=screenshot_path, type='png')
                            logger.info(f"QR code element screenshot saved to: {screenshot_path}")
                    else:
                        # If QR element not found, try to find and extract just the canvas
                        logger.warning("QR element not found, attempting to find canvas directly...")
                        try:
                            # Wait a bit more for QR code to render
                            await asyncio.sleep(2)
                            
                            # Try to find the QR code canvas (square, 200-400px)
                            all_canvases = await self.page.query_selector_all('canvas')
                            logger.info(f"Found {len(all_canvases)} canvas elements")
                            
                            if all_canvases:
                                qr_canvas = None
                                for canvas in all_canvases:
                                    try:
                                        box = await canvas.bounding_box()
                                        if box:
                                            width = box['width']
                                            height = box['height']
                                            size = width * height
                                            
                                            # QR codes are typically square (within 50px difference) and 150-500px
                                            is_square = abs(width - height) < 50
                                            is_reasonable_size = 150 < width < 500 and 150 < height < 500
                                            
                                            if is_square and is_reasonable_size and size > 40000:  # At least ~200x200
                                                qr_canvas = canvas
                                                logger.info(f"Found QR code canvas: {width}x{height} (size: {size})")
                                                break
                                    except:
                                        continue
                                
                                if qr_canvas:
                                    # Screenshot ONLY the canvas element
                                    await qr_canvas.screenshot(path=screenshot_path, type='png', scale='device')
                                    logger.info("Captured QR code canvas element only")
                                    qr_element = qr_canvas  # Set for later processing
                                else:
                                    logger.error("No suitable QR code canvas found (looking for square canvas 150-500px)")
                                    return None
                            else:
                                logger.error("No canvas elements found on page")
                                return None
                        except Exception as e:
                            logger.error(f"Failed to extract QR code canvas: {str(e)}")
                            import traceback
                            logger.error(traceback.format_exc())
                            return None
                    
                    # Read and encode the screenshot
                    with open(screenshot_path, 'rb') as f:
                        img_data = f.read()
                        qr_base64 = base64.b64encode(img_data).decode('utf-8')
                    
                    if qr_base64 and len(qr_base64) > 1000:
                        logger.info(f"QR code extracted successfully using Playwright (base64 length: {len(qr_base64)})")
                        return qr_base64
                    else:
                        raise Exception("Invalid screenshot data")
                        
                except Exception as e:
                    logger.error(f"Playwright QR code extraction failed: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return None
            else:
                raise Exception("Playwright not available")
                
        except Exception as e:
            logger.error(f"Error getting QR code: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def get_messages(self, limit: int = 50) -> Tuple[List[WhatsAppMessage], int]:
        """
        Retrieve WhatsApp messages
        
        Args:
            limit: Maximum number of messages to retrieve
            
        Returns:
            Tuple of (messages list, total count)
        """
        try:
            # Initialize browser/driver if needed
            if PLAYWRIGHT_AVAILABLE:
                if not self.browser or not self.page:
                    await self._create_browser()
                    await self.initialize()
            else:
                raise Exception("Playwright not available")
            
            # Check connection
            is_connected = await self._check_connection_status()
            if not is_connected:
                raise Exception("WhatsApp Web is not connected. Please scan the QR code first.")
            
            # Ensure we're on the main WhatsApp Web page and refresh if needed
            current_url = self.page.url if self.page else ""
            if 'web.whatsapp.com' not in current_url:
                logger.info("Not on WhatsApp Web, navigating...")
                await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            else:
                # Refresh the page to ensure we have the latest state
                logger.info("Refreshing WhatsApp Web page to ensure latest state...")
                try:
                    await self.page.reload(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.debug(f"Page refresh failed, continuing anyway: {str(e)}")
            
            # Wait for chat list to be ready - try multiple selectors
            if PLAYWRIGHT_AVAILABLE and self.page:
                chat_list_found = False
                selectors_to_try = [
                    '[data-testid="chatlist"]',
                    '[data-testid="conversation-list"]',
                    '#pane-side',
                    '[role="listbox"]',
                    'div[aria-label*="Chat"]',
                    'div[aria-label*="chat"]',
                ]
                
                for selector in selectors_to_try:
                    try:
                        await self.page.wait_for_selector(selector, timeout=3000)
                        logger.info(f"Chat list found using selector: {selector}")
                        chat_list_found = True
                        break
                    except PlaywrightTimeout:
                        continue
                
                if not chat_list_found:
                    # Try to find chat items directly
                    await asyncio.sleep(2)
                    chat_items = await self.page.query_selector_all('[data-testid="cell-frame-container"], [role="listitem"]')
                    if chat_items and len(chat_items) > 0:
                        logger.info(f"Found {len(chat_items)} chat items directly")
                        chat_list_found = True
                
                if not chat_list_found:
                    # Check if we're actually connected by looking for main app elements
                    main_app = await self.page.query_selector('#app > div:not(.landing-wrapper)')
                    landing = await self.page.query_selector('.landing-wrapper')
                    if landing or not main_app:
                        raise Exception("WhatsApp Web is not connected. Please scan the QR code first.")
                    else:
                        logger.warning("Chat list selector not found, but main app is present. Continuing anyway...")
            
            # Get messages from all chats
            messages = await self._fetch_messages_from_web(limit)
            
            logger.info(f"Retrieved {len(messages)} WhatsApp messages")
            return messages, len(messages)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching WhatsApp messages: {error_msg}")
            raise Exception(f"Failed to fetch WhatsApp messages: {error_msg}")
    
    async def _fetch_messages_from_web(self, limit: int) -> List[WhatsAppMessage]:
        """Fetch messages from WhatsApp Web"""
        messages = []
        
        try:
            # Wait for page to be fully loaded
            await asyncio.sleep(2)
            
            # Ensure we're on the main chat list view (not in a conversation)
            # Check if we're in a conversation and go back if needed
            try:
                conversation_panel = await self.page.query_selector('[data-testid="conversation-panel-wrapper"]')
                if conversation_panel:
                    # We're in a conversation, go back to chat list
                    back_button = await self.page.query_selector('[data-testid="back"]')
                    if back_button:
                        await back_button.click()
                        await asyncio.sleep(1)
                    else:
                        # Try using keyboard or history
                        await self.page.keyboard.press('Escape')
                        await asyncio.sleep(1)
            except:
                pass
            
            # Scroll the chat list to load all chats
            try:
                chat_list_container = await self.page.query_selector('#pane-side, [data-testid="chatlist"], [data-testid="conversation-list"]')
                if chat_list_container:
                    # Scroll down multiple times to load all chats
                    previous_count = 0
                    scroll_attempts = 0
                    max_scrolls = 20
                    
                    while scroll_attempts < max_scrolls:
                        # Get current chat count
                        current_items = await chat_list_container.query_selector_all('[data-testid="cell-frame-container"], [role="listitem"]')
                        current_count = len(current_items) if current_items else 0
                        
                        if current_count == previous_count and scroll_attempts > 3:
                            # No new chats loaded, we've reached the end
                            break
                        
                        previous_count = current_count
                        
                        # Scroll to bottom
                        await chat_list_container.evaluate('element => element.scrollTop = element.scrollHeight')
                        await asyncio.sleep(0.5)  # Wait for new chats to load
                        scroll_attempts += 1
                    
                    logger.info(f"Scrolled chat list {scroll_attempts} times, found {previous_count} total chats")
            except Exception as e:
                logger.debug(f"Error scrolling chat list: {str(e)}")
            
            # Get all chat items from the chat list - try multiple selectors
            chat_items = []
            selectors_to_try = [
                '[data-testid="cell-frame-container"]',
                '[role="listitem"]',
                'div[aria-label*="Chat"]',
                '#pane-side > div > div > div',
            ]
            
            for selector in selectors_to_try:
                try:
                    items = await self.page.query_selector_all(selector)
                    if items and len(items) > 0:
                        # Filter to only visible, clickable chat items
                        seen_ids = set()
                        for item in items:
                            try:
                                box = await item.bounding_box()
                                if box and box['width'] > 0 and box['height'] > 0:
                                    # Get a unique identifier to avoid duplicates
                                    item_id = await item.evaluate('el => el.getAttribute("data-id") || el.outerHTML.substring(0, 100)')
                                    if item_id not in seen_ids:
                                        chat_items.append(item)
                                        seen_ids.add(item_id)
                            except:
                                continue
                        if chat_items:
                            logger.info(f"Found {len(chat_items)} unique chat items using selector: {selector}")
                            break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {str(e)}")
                    continue
            
            if not chat_items:
                logger.warning("No chat items found. Page might still be loading or no chats available.")
                # Return empty list instead of error - user might not have any chats
                return messages
            
            logger.info(f"Found {len(chat_items)} unique chats to process")
            
            # Process all chats (removed limit to show all messages)
            max_chats = len(chat_items)  # Process all chats
            
            for idx in range(max_chats):
                try:
                    # Get chat info before clicking (to get phone number if available)
                    chat_name = "Unknown"
                    chat_phone = None
                    try:
                        # Try to get chat name and phone from the chat list item
                        chat_item_text = await chat_items[idx].inner_text()
                        chat_item_html = await chat_items[idx].evaluate('el => el.outerHTML')
                        
                        # Try to extract phone number from the chat item
                        # Phone numbers in WhatsApp are usually in spans with specific attributes
                        phone_elem = await chat_items[idx].query_selector('span[title*="+"], span[title*="@"]')
                        if phone_elem:
                            phone_title = await phone_elem.get_attribute("title")
                            if phone_title:
                                # Extract phone number from title (format: "Name\n+1234567890")
                                parts = phone_title.split('\n')
                                if len(parts) > 1:
                                    chat_phone = parts[-1].strip()
                                    chat_name = parts[0].strip() if parts[0].strip() else chat_phone
                                else:
                                    # Check if it's a phone number format
                                    if '+' in phone_title or phone_title.replace(' ', '').replace('-', '').isdigit():
                                        chat_phone = phone_title.strip()
                                        chat_name = chat_phone
                        
                        # If no phone found, try to get name from span with title
                        if chat_name == "Unknown":
                            name_elem = await chat_items[idx].query_selector('span[title]')
                            if name_elem:
                                title = await name_elem.get_attribute("title")
                                if title:
                                    # Split by newline to separate name and phone
                                    parts = title.split('\n')
                                    if len(parts) > 0:
                                        chat_name = parts[0].strip()
                                    if len(parts) > 1:
                                        chat_phone = parts[-1].strip()
                    except Exception as e:
                        logger.debug(f"Error getting chat info from list: {str(e)}")
                    
                    # Click on the chat item
                    await chat_items[idx].click()
                    await asyncio.sleep(2)  # Wait longer for chat to fully load
                    
                    # Wait for messages to appear
                    try:
                        await self.page.wait_for_selector('[data-testid="msg-container"], [data-testid="msg"], div[data-id]', timeout=5000)
                    except:
                        logger.debug(f"Timeout waiting for messages in chat {idx}, continuing anyway...")
                    
                    # Get chat name from header (more reliable after clicking)
                    try:
                        chat_name_elem = await self.page.query_selector('[data-testid="conversation-header"] span[title], [data-testid="conversation-header"] span')
                        if chat_name_elem:
                            header_text = await chat_name_elem.inner_text()
                            header_title = await chat_name_elem.get_attribute("title")
                            
                            if header_title:
                                # Title often contains "Name\nPhone"
                                parts = header_title.split('\n')
                                if len(parts) > 0:
                                    new_name = parts[0].strip()
                                    if new_name:
                                        chat_name = new_name
                                if len(parts) > 1:
                                    new_phone = parts[-1].strip()
                                    if new_phone and ('+' in new_phone or new_phone.replace(' ', '').replace('-', '').isdigit()):
                                        chat_phone = new_phone
                            elif header_text:
                                chat_name = header_text.strip()
                    except:
                        pass
                    
                    # Use phone number as chat_name if name is still Unknown
                    if chat_name == "Unknown" and chat_phone:
                        chat_name = chat_phone
                    
                    # Scroll up to load more messages and collect all messages
                    logger.info(f"Loading messages from chat {idx}: {chat_name}")
                    message_elements = []
                    seen_message_ids = set()  # Track unique messages by their data-id
                    
                    # Find the message container/scrollable area
                    scroll_container = None
                    scroll_selectors = [
                        '[data-testid="conversation-panel-messages"]',
                        '#main > div > div',
                        '[role="log"]',
                        '.message-list',
                        '#main'
                    ]
                    
                    for scroll_selector in scroll_selectors:
                        try:
                            container = await self.page.query_selector(scroll_selector)
                            if container:
                                scroll_container = container
                                logger.debug(f"Found scroll container: {scroll_selector}")
                                break
                        except:
                            continue
                    
                    if not scroll_container:
                        # Fallback: use page
                        scroll_container = self.page
                    
                    # First, get all currently visible messages without scrolling
                    message_selectors = [
                        '[data-testid="msg-container"]',
                        '[data-testid="msg"]',
                        'div[data-id]',
                        '.message',
                        '[role="row"]',
                    ]
                    
                    # Get initial messages
                    for msg_selector in message_selectors:
                        try:
                            elements = await self.page.query_selector_all(msg_selector)
                            if elements and len(elements) > 0:
                                for elem in elements:
                                    try:
                                        box = await elem.bounding_box()
                                        if box and box['width'] > 0 and box['height'] > 0:
                                            msg_id = await elem.get_attribute("data-id")
                                            if not msg_id:
                                                try:
                                                    msg_text = await elem.inner_text()
                                                    msg_id = f"{msg_text[:50]}" if msg_text else f"msg_{len(message_elements)}"
                                                except:
                                                    msg_id = f"msg_{len(message_elements)}"
                                            
                                            if msg_id not in seen_message_ids:
                                                message_elements.append(elem)
                                                seen_message_ids.add(msg_id)
                                    except:
                                        continue
                                if message_elements:
                                    logger.debug(f"Found {len(message_elements)} initial messages using selector: {msg_selector}")
                                    break
                        except:
                            continue
                    
                    # Scroll up to load older messages (simplified approach)
                    max_scrolls = 15  # Reduced scroll attempts
                    scroll_count = 0
                    no_new_messages_count = 0
                    
                    while scroll_count < max_scrolls and len(message_elements) < limit:
                        previous_count = len(message_elements)
                        
                        # Scroll up
                        try:
                            await scroll_container.evaluate('''
                                element => {
                                    const panel = element.querySelector('[data-testid="conversation-panel-messages"]') || 
                                                 element.querySelector('[role="log"]') ||
                                                 element;
                                    if (panel) {
                                        panel.scrollTop = 0;
                                    }
                                }
                            ''')
                            await asyncio.sleep(1)  # Wait for messages to load
                        except:
                            try:
                                await self.page.keyboard.press('Home')
                                await asyncio.sleep(1)
                            except:
                                await asyncio.sleep(0.5)
                        
                        # Get new messages after scroll
                        for msg_selector in message_selectors:
                            try:
                                elements = await self.page.query_selector_all(msg_selector)
                                if elements:
                                    for elem in elements:
                                        try:
                                            box = await elem.bounding_box()
                                            if box and box['width'] > 0 and box['height'] > 0:
                                                msg_id = await elem.get_attribute("data-id")
                                                if not msg_id:
                                                    try:
                                                        msg_text = await elem.inner_text()
                                                        msg_id = f"{msg_text[:50]}" if msg_text else f"msg_{len(message_elements)}"
                                                    except:
                                                        msg_id = f"msg_{len(message_elements)}"
                                                
                                                if msg_id not in seen_message_ids:
                                                    message_elements.append(elem)
                                                    seen_message_ids.add(msg_id)
                                        except:
                                            continue
                                    break
                            except:
                                continue
                        
                        # Check if we got new messages
                        if len(message_elements) > previous_count:
                            no_new_messages_count = 0
                            logger.debug(f"Scroll {scroll_count}: Found {len(message_elements) - previous_count} new messages (total: {len(message_elements)})")
                        else:
                            no_new_messages_count += 1
                            if no_new_messages_count >= 2:  # Reduced from 3 to 2
                                logger.debug(f"Reached top of chat after {scroll_count} scrolls")
                                break
                        
                        scroll_count += 1
                    
                    logger.info(f"Collected {len(message_elements)} unique messages from chat {idx} after {scroll_count} scrolls")
                    
                    if not message_elements:
                        logger.debug(f"No messages found in chat {idx}, skipping...")
                        # Go back to chat list
                        try:
                            back_button = await self.page.query_selector('[data-testid="back"]')
                            if back_button:
                                await back_button.click()
                                await asyncio.sleep(0.5)
                        except:
                            pass
                        continue
                    
                    # Process all messages from this chat (up to remaining limit)
                    messages_processed_so_far = len(messages)
                    remaining_limit = max(0, limit - messages_processed_so_far)
                    
                    # Process all messages if we haven't hit the total limit
                    messages_to_process = message_elements if remaining_limit == 0 or remaining_limit >= len(message_elements) else message_elements[:remaining_limit]
                    
                    for msg_idx, msg_elem in enumerate(messages_to_process):
                        try:
                            # Get message text - try multiple methods
                            body = ""
                            try:
                                # Method 1: Try data-testid="msg-text"
                                text_elem = await msg_elem.query_selector('[data-testid="msg-text"]')
                                if text_elem:
                                    body = await text_elem.inner_text()
                                    body = body.strip()
                            except:
                                pass
                            
                            # Method 2: Try span with selectable text
                            if not body:
                                try:
                                    text_spans = await msg_elem.query_selector_all('span.selectable-text, span[dir="ltr"], span[dir="rtl"]')
                                    if text_spans:
                                        texts = []
                                        for span in text_spans:
                                            span_text = await span.inner_text()
                                            if span_text:
                                                texts.append(span_text.strip())
                                        if texts:
                                            body = ' '.join(texts).strip()
                                except:
                                    pass
                            
                            # Method 3: Get all text from element (excluding time and metadata)
                            if not body:
                                try:
                                    # Get all text but exclude time and other metadata
                                    all_text = await msg_elem.inner_text()
                                    if all_text:
                                        # Remove common metadata patterns
                                        lines = all_text.split('\n')
                                        filtered_lines = []
                                        for line in lines:
                                            line = line.strip()
                                            # Skip time patterns (e.g., "8:15 AM", "Yesterday")
                                            if not re.match(r'^\d{1,2}:\d{2}\s*(AM|PM)$', line) and \
                                               line.lower() not in ['yesterday', 'today', 'read', 'delivered'] and \
                                               not line.startswith('✓'):
                                                filtered_lines.append(line)
                                        body = ' '.join(filtered_lines).strip()
                                except:
                                    pass
                            
                            # Method 4: Last resort - get any text content
                            if not body:
                                try:
                                    body = await msg_elem.evaluate('el => el.textContent || el.innerText || ""')
                                    body = body.strip()
                                except:
                                    pass
                            
                            # Debug: Log element structure
                            try:
                                elem_html = await msg_elem.evaluate('el => el.outerHTML.substring(0, 200)')
                                elem_classes = await msg_elem.get_attribute("class")
                                logger.debug(f"Message element classes: {elem_classes}, HTML preview: {elem_html}")
                            except:
                                pass
                            
                            # Check if message is sent by me - use JavaScript evaluation for comprehensive detection
                            from_name = None
                            is_sent = False
                            
                            try:
                                # Use JavaScript to comprehensively check the message element and its ancestors
                                detection_result = await msg_elem.evaluate("""
                                (element) => {
                                    let isSent = false;
                                    let fromName = null;
                                    
                                    // Function to check element and all ancestors
                                    function checkElement(el) {
                                        if (!el) return false;
                                        
                                        // Check data attributes (most reliable)
                                        const dataFromMe = el.getAttribute('data-from-me');
                                        if (dataFromMe === 'true' || dataFromMe === '1' || dataFromMe === true) {
                                            return true;
                                        }
                                        
                                        // Check data-id for outgoing pattern
                                        const dataId = el.getAttribute('data-id');
                                        if (dataId && (dataId.includes('true') || dataId.includes('out'))) {
                                            return true;
                                        }
                                        
                                        // Check class names
                                        const classes = el.className || '';
                                        const sentIndicators = ['message-out', 'out', 'sent', 'message-sent', 'msg-out', 'message-outgoing', 'outgoing', 'message-out', 'msg-container-out'];
                                        for (let indicator of sentIndicators) {
                                            if (classes.toLowerCase().includes(indicator.toLowerCase())) {
                                                return true;
                                            }
                                        }
                                        
                                        // Check aria-label
                                        const ariaLabel = el.getAttribute('aria-label') || '';
                                        if (ariaLabel && (ariaLabel.toLowerCase().includes('sent') || 
                                            ariaLabel.toLowerCase().includes('you') || 
                                            ariaLabel.toLowerCase().includes('outgoing'))) {
                                            return true;
                                        }
                                        
                                        // Check data-testid
                                        const testId = el.getAttribute('data-testid') || '';
                                        if (testId && (testId.includes('out') || testId.includes('sent'))) {
                                            return true;
                                        }
                                        
                                        return false;
                                    }
                                    
                                    // Check element and all ancestors up to 6 levels (more thorough)
                                    let current = element;
                                    let level = 0;
                                    while (current && level < 6) {
                                        if (checkElement(current)) {
                                            isSent = true;
                                            fromName = 'You';
                                            break;
                                        }
                                        current = current.parentElement;
                                        level++;
                                    }
                                    
                                    // If still not detected, check by position and alignment
                                    if (!isSent) {
                                        let container = element;
                                        let containerLevel = 0;
                                        while (container && containerLevel < 5) {
                                            const style = window.getComputedStyle(container);
                                            const justifyContent = style.justifyContent;
                                            const flexDirection = style.flexDirection;
                                            
                                            // Check if container is right-aligned
                                            if (justifyContent === 'flex-end') {
                                                const rect = container.getBoundingClientRect();
                                                const pageWidth = window.innerWidth;
                                                
                                                // If message is on the right side (more than 45% from left), likely sent
                                                if (rect.left > pageWidth * 0.45) {
                                                    isSent = true;
                                                    fromName = 'You';
                                                    break;
                                                }
                                            }
                                            
                                            container = container.parentElement;
                                            containerLevel++;
                                        }
                                    }
                                    
                                    // If not sent, try to get sender name
                                    if (!isSent) {
                                        // Look for sender name in various places
                                        const senderSelectors = [
                                            '[data-testid="msg-sender"]',
                                            '.message-author',
                                            'span[title]',
                                            '[data-testid="conversation-header"] span'
                                        ];
                                        
                                        for (let selector of senderSelectors) {
                                            const sender = element.querySelector(selector);
                                            if (sender) {
                                                fromName = sender.innerText || sender.textContent;
                                                fromName = fromName ? fromName.trim() : null;
                                                if (fromName) break;
                                            }
                                        }
                                        
                                        // Also check parent containers for sender info
                                        if (!fromName) {
                                            let parent = element.parentElement;
                                            let parentLevel = 0;
                                            while (parent && parentLevel < 3) {
                                                const sender = parent.querySelector('[data-testid="msg-sender"], .message-author');
                                                if (sender) {
                                                    fromName = sender.innerText || sender.textContent;
                                                    fromName = fromName ? fromName.trim() : null;
                                                    if (fromName) break;
                                                }
                                                parent = parent.parentElement;
                                                parentLevel++;
                                            }
                                        }
                                    }
                                    
                                    return { isSent, fromName };
                                }
                            """)
                                
                                is_sent = detection_result.get('isSent', False)
                                from_name = detection_result.get('fromName')
                                
                                # If JavaScript detection didn't find sender name and it's not sent, use chat name or phone
                                if not is_sent:
                                    if not from_name:
                                        # Use chat name, or phone number if available
                                        from_name = chat_name if chat_name != "Unknown" else (chat_phone if chat_phone else "Unknown")
                                    # If from_name is empty or just whitespace, use chat info
                                    if not from_name or from_name.strip() == "":
                                        from_name = chat_name if chat_name != "Unknown" else (chat_phone if chat_phone else "Unknown")
                                elif is_sent:
                                    from_name = "You"
                                
                                logger.debug(f"Detection result: is_sent={is_sent}, from_name='{from_name}', chat_name='{chat_name}', chat_phone='{chat_phone}'")
                                
                            except Exception as e:
                                logger.warning(f"Error determining message sender: {str(e)}")
                                from_name = chat_name if chat_name != "Unknown" else (chat_phone if chat_phone else "Unknown")
                                is_sent = False
                            
                            # Log final determination
                            logger.info(f"Message {msg_idx}: from_name='{from_name}', is_sent={is_sent}, body='{body[:50] if body else 'NO BODY'}'")
                            
                            # Get timestamp
                            timestamp_str = datetime.now().isoformat()
                            try:
                                time_elem = await msg_elem.query_selector('[data-testid="msg-time"]')
                                if time_elem:
                                    timestamp_str = await time_elem.get_attribute("title") or await time_elem.inner_text()
                            except:
                                pass
                            
                            # Add message if it has body text or if we can identify the sender
                            # Don't skip messages just because body is empty - might be media or system message
                            if body or from_name or True:  # Always add, we'll handle empty bodies
                                # Generate message ID
                                message_id = f"{chat_name}_{idx}_{msg_idx}"
                                
                                # Use phone number for from_number if available, otherwise use chat_name
                                message_from_number = chat_phone if chat_phone else (chat_name if chat_name != "Unknown" else "Unknown")
                                
                                # Handle empty body (might be media, system message, etc.)
                                if not body:
                                    body = "[Media or System Message]"
                                
                                # Create WhatsAppMessage
                                message = WhatsAppMessage(
                                    message_id=message_id,
                                    from_number=message_from_number,
                                    from_name=from_name if from_name and from_name != "Unknown" else message_from_number,
                                    body=body,
                                    timestamp=timestamp_str,
                                    is_read=True,
                                    is_sent=is_sent,  # Set is_sent flag
                                    chat_id=chat_name if chat_name != "Unknown" else message_from_number,
                                    chat_name=chat_name if chat_name != "Unknown" else message_from_number
                                )
                                
                                # Log for debugging
                                logger.debug(f"Created message: from_name='{from_name}', is_sent={is_sent}, body='{body[:50] if body else 'NO BODY'}'")
                                
                                messages.append(message)
                                
                                if len(messages) >= limit:
                                    break
                                
                        except Exception as e:
                            logger.warning(f"Error parsing message: {str(e)}")
                            continue
                    
                    # Go back to chat list
                    try:
                        back_button = await self.page.query_selector('[data-testid="back"]')
                        if back_button:
                            await back_button.click()
                            await asyncio.sleep(0.5)
                    except:
                        # Try alternative way to go back
                        await self.page.evaluate("window.history.back()")
                        await asyncio.sleep(0.5)
                    
                    if len(messages) >= limit:
                        break
                        
                except Exception as e:
                    logger.warning(f"Error processing chat {idx}: {str(e)}")
                    continue
            
            return messages
            
        except Exception as e:
            logger.error(f"Error fetching messages from WhatsApp Web: {str(e)}")
            raise
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check WhatsApp connection status
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        try:
            # Initialize browser/driver if not already initialized
            if PLAYWRIGHT_AVAILABLE:
                if not self.browser or not self.page:
                    logger.info("Browser not initialized, creating browser...")
                    try:
                        await self._create_browser()
                        await self.initialize()
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Failed to create browser: {error_msg}")
                        import traceback
                        logger.error(traceback.format_exc())
                        return False, error_msg
            
            is_connected = await self._check_connection_status()
            
            if is_connected:
                return True, "WhatsApp Web is connected"
            else:
                return False, "WhatsApp Web is not connected. Please scan the QR code."
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error checking WhatsApp connection status: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"Error checking status: {error_msg}"
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if PLAYWRIGHT_AVAILABLE:
                if self.browser:
                    # For persistent context, we need to close it properly
                    await self.browser.close()
                    self.browser = None
                if self.playwright:
                    await self.playwright.stop()
                    self.playwright = None
                self.page = None
                logger.info("Playwright browser closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        
        self.is_connected = False
        logger.info("WhatsApp service cleanup completed")

