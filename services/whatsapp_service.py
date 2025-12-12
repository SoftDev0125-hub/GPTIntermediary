"""
WhatsApp Service
Handles WhatsApp message retrieval and operations using WhatsApp Web (for personal accounts)
"""

import logging
import os
import aiohttp
import asyncio
import base64
import json
from typing import List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time

from models.schemas import WhatsAppMessage

load_dotenv()
logger = logging.getLogger(__name__)

# WhatsApp Cloud API Configuration (for business accounts - optional)
WHATSAPP_API_VERSION = "v21.0"
WHATSAPP_API_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


class WhatsAppService:
    """Service for handling WhatsApp operations using WhatsApp Web (personal accounts)"""
    
    def __init__(self):
        """Initialize WhatsApp service"""
        load_dotenv(override=True)
        # Cloud API credentials (optional, for business accounts)
        self.access_token = os.getenv('WHATSAPP_ACCESS_TOKEN', '')
        self.phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
        self.business_account_id = os.getenv('WHATSAPP_BUSINESS_ACCOUNT_ID', '')
        self.app_id = os.getenv('WHATSAPP_APP_ID', '')
        self.app_secret = os.getenv('WHATSAPP_APP_SECRET', '')
        
        # WhatsApp Web (personal accounts)
        self.driver = None
        self.is_connected = False
        self.session_dir = os.path.join(os.path.dirname(__file__), '..', 'whatsapp_session')
        os.makedirs(self.session_dir, exist_ok=True)
        
        # Check if using Cloud API or WhatsApp Web
        self.use_cloud_api = bool(self.access_token and self.phone_number_id)
        
        if not self.use_cloud_api:
            logger.info("WhatsApp Web mode (personal accounts). Cloud API not configured.")
        else:
            logger.info("WhatsApp Cloud API service initialized (business accounts)")
    
    async def initialize(self):
        """Initialize WhatsApp connection (Cloud API or Web)"""
        if self.use_cloud_api:
            # Verify Cloud API credentials
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}"
                    headers = {
                        'Authorization': f'Bearer {self.access_token}'
                    }
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            logger.info("WhatsApp Cloud API connection verified")
                        else:
                            error_text = await response.text()
                            logger.error(f"WhatsApp Cloud API verification failed: {error_text}")
            except Exception as e:
                logger.error(f"Error verifying WhatsApp Cloud API: {str(e)}")
        else:
            # Initialize WhatsApp Web
            await self._initialize_whatsapp_web()
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                logger.info("WhatsApp Web driver closed")
            except Exception as e:
                logger.warning(f"Error closing driver: {str(e)}")
        logger.info("WhatsApp service cleanup completed")
    
    async def get_messages(
        self,
        limit: int = 50,
        access_token: Optional[str] = None
    ) -> tuple[List[WhatsAppMessage], int]:
        """
        Retrieve WhatsApp messages
        
        Args:
            limit: Maximum number of messages to retrieve
            access_token: Optional access token (for Cloud API only)
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            # Try Cloud API first if configured
            if self.use_cloud_api and (access_token or self.access_token):
                try:
                    logger.info(f"Fetching {limit} WhatsApp messages from Cloud API")
                    messages = await self._fetch_messages_from_api(access_token or self.access_token, limit)
                    logger.info(f"Retrieved {len(messages)} WhatsApp messages from Cloud API")
                    return messages, len(messages)
                except Exception as cloud_error:
                    error_msg = str(cloud_error)
                    # Check if it's an authentication error
                    if "OAuth" in error_msg or "access token" in error_msg.lower() or "invalid" in error_msg.lower() or "2190" in error_msg:
                        logger.warning(f"Cloud API authentication failed: {error_msg}")
                        logger.info("Falling back to WhatsApp Web (personal accounts)")
                        # Fall through to WhatsApp Web
                    else:
                        # Re-raise other Cloud API errors
                        raise
            
            # Use WhatsApp Web (personal accounts) - either as fallback or primary method
            logger.info(f"Fetching {limit} WhatsApp messages from WhatsApp Web")
            
            # Ensure driver is valid before proceeding
            if self.driver:
                try:
                    # Check if driver session is still valid
                    _ = self.driver.current_url
                except Exception as driver_check_error:
                    logger.warning(f"Driver session is invalid, recreating: {str(driver_check_error)}")
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                    self.is_connected = False
            
            messages = await self._fetch_messages_from_web(limit)
            logger.info(f"Retrieved {len(messages)} WhatsApp messages from WhatsApp Web")
            return messages, len(messages)
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching WhatsApp messages: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Provide more helpful error messages
            if "connection refused" in error_msg.lower() or "httpconnectionpool" in error_msg.lower() or "session" in error_msg.lower():
                # Driver session was lost, try to recreate
                logger.warning("ChromeDriver session was lost, attempting to recreate...")
                try:
                    if self.driver:
                        try:
                            self.driver.quit()
                        except:
                            pass
                    self.driver = None
                    self.is_connected = False
                    # Try once more with fresh driver
                    logger.info("Retrying with fresh driver session...")
                    messages = await self._fetch_messages_from_web(limit)
                    logger.info(f"Retrieved {len(messages)} WhatsApp messages after driver recreation")
                    return messages, len(messages)
                except Exception as retry_error:
                    raise Exception(f"ChromeDriver session was lost and could not be recreated. Please restart the backend server. Error: {str(retry_error)}")
            elif "not connected" in error_msg.lower() or "qr code" in error_msg.lower():
                raise Exception(f"WhatsApp Web is not connected. Please scan the QR code first. Error: {error_msg}")
            elif "timeout" in error_msg.lower():
                raise Exception(f"Timeout waiting for WhatsApp Web to load. Please make sure WhatsApp Web is connected and try again. Error: {error_msg}")
            elif "driver" in error_msg.lower() or "browser" in error_msg.lower():
                raise Exception(f"Browser driver error. Please check if Chrome is installed and try again. Error: {error_msg}")
            else:
                raise Exception(f"Failed to fetch WhatsApp messages: {error_msg}")
    
    async def _fetch_messages_from_api(self, access_token: str, limit: int) -> List[WhatsAppMessage]:
        """Fetch messages from WhatsApp Cloud API"""
        messages = []
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {access_token}'
                }
                
                # WhatsApp Cloud API: Get conversations
                # Note: This endpoint may require specific permissions
                conversations_url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}/conversations"
                
                try:
                    async with session.get(
                        conversations_url, 
                        headers=headers, 
                        params={'limit': limit, 'fields': 'id,participants'}
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            conversations = data.get('data', [])
                            
                            logger.info(f"Found {len(conversations)} conversations")
                            
                            # For each conversation, get latest message
                            for conv in conversations[:limit]:
                                try:
                                    conversation_id = conv.get('id', '')
                                    participants = conv.get('participants', {}).get('data', [])
                                    
                                    if not participants:
                                        continue
                                    
                                    participant = participants[0]
                                    participant_name = participant.get('name', 'Unknown')
                                    participant_wa_id = participant.get('wa_id', '')
                                    
                                    # Get messages for this conversation
                                    messages_url = f"{WHATSAPP_API_BASE_URL}/{conversation_id}/messages"
                                    async with session.get(
                                        messages_url, 
                                        headers=headers, 
                                        params={'limit': 1, 'fields': 'id,from,timestamp,type,text,status'}
                                    ) as msg_response:
                                        if msg_response.status == 200:
                                            msg_data = await msg_response.json()
                                            msg_list = msg_data.get('data', [])
                                            
                                            if msg_list:
                                                latest_msg = msg_list[0]
                                                message = self._parse_cloud_api_message(
                                                    latest_msg, 
                                                    participant_name, 
                                                    participant_wa_id, 
                                                    conversation_id
                                                )
                                                messages.append(message)
                                        elif msg_response.status == 404:
                                            # Conversation might not have messages yet
                                            logger.debug(f"No messages in conversation {conversation_id}")
                                        else:
                                            error_text = await msg_response.text()
                                            logger.warning(f"Error getting messages for conversation {conversation_id}: {error_text}")
                                except Exception as conv_error:
                                    logger.warning(f"Error processing conversation: {str(conv_error)}")
                                    continue
                        elif response.status == 403:
                            error_text = await response.text()
                            logger.error(f"Permission denied: {error_text}")
                            raise Exception("WhatsApp API permission denied. Check your access token permissions.")
                        elif response.status == 401:
                            error_text = await response.text()
                            logger.error(f"Unauthorized: {error_text}")
                            # Try to parse error message
                            try:
                                error_data = await response.json()
                                error_detail = error_data.get('error', {})
                                error_message = error_detail.get('message', 'Invalid access token')
                                error_code = error_detail.get('code', '')
                                raise Exception(f"Cloud API authentication failed (Code {error_code}): {error_message}. Please check your WHATSAPP_ACCESS_TOKEN in .env file or remove it to use WhatsApp Web instead.")
                            except:
                                raise Exception(f"Invalid access token. Please check your WHATSAPP_ACCESS_TOKEN in .env file or remove it to use WhatsApp Web instead. Error: {error_text}")
                        else:
                            error_text = await response.text()
                            logger.error(f"WhatsApp API error ({response.status}): {error_text}")
                            # Try alternative: return empty list with helpful message
                            raise Exception(f"WhatsApp API error: {error_text}")
                except aiohttp.ClientError as http_error:
                    logger.error(f"HTTP error: {str(http_error)}")
                    raise Exception(f"Network error connecting to WhatsApp API: {str(http_error)}")
        
        except Exception as e:
            # Re-raise if it's already a formatted exception
            if "WhatsApp API" in str(e) or "Network error" in str(e):
                raise
            # Otherwise wrap it
            logger.error(f"Unexpected error fetching messages: {str(e)}")
            raise Exception(f"Failed to fetch messages: {str(e)}")
        
        return messages
    
    def _parse_cloud_api_message(self, raw_message: dict, participant_name: str, participant_wa_id: str, conversation_id: str) -> WhatsAppMessage:
        """Parse WhatsApp Cloud API message into WhatsAppMessage model"""
        message_id = raw_message.get('id', '')
        timestamp = raw_message.get('timestamp', '')
        
        # Convert timestamp to readable format
        if timestamp:
            try:
                dt = datetime.fromtimestamp(int(timestamp))
                timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                timestamp_str = timestamp
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get message body
        body = ''
        msg_type = raw_message.get('type', '')
        
        if msg_type == 'text':
            body = raw_message.get('text', {}).get('body', '')
        elif msg_type == 'image':
            body = f"[Image] {raw_message.get('image', {}).get('caption', '')}"
        elif msg_type == 'video':
            body = "[Video]"
        elif msg_type == 'audio':
            body = "[Audio]"
        elif msg_type == 'document':
            body = f"[Document] {raw_message.get('document', {}).get('filename', '')}"
        else:
            body = f"[{msg_type}]"
        
        return WhatsAppMessage(
            message_id=message_id,
            from_number=participant_wa_id,
            from_name=participant_name,
            body=body,
            timestamp=timestamp_str,
            is_read=raw_message.get('status') == 'read',
            chat_id=conversation_id,
            chat_name=participant_name
        )
    
    def _create_driver(self):
        """Create and configure Chrome driver for WhatsApp Web"""
        if self.driver:
            try:
                # Check if driver is still valid
                self.driver.current_url
                return self.driver
            except:
                # Driver is invalid, reset it
                self.driver = None
        
        try:
            chrome_options = Options()
            
            # Basic options for stability
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-software-rasterizer')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--remote-debugging-port=9222')
            
            # Prevent automation detection
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_experimental_option("detach", True)
            
            # User agent to avoid detection
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Use user data directory to persist session (with proper path handling for Windows)
            user_data_dir = os.path.join(os.path.abspath(self.session_dir), 'chrome_user_data')
            # Normalize path for Windows
            user_data_dir = os.path.normpath(user_data_dir)
            chrome_options.add_argument(f'--user-data-dir={user_data_dir}')
            
            # Headless mode (set to False to see browser)
            headless = os.getenv('WHATSAPP_HEADLESS', 'true').lower() == 'true'
            if headless:
                chrome_options.add_argument('--headless=new')  # Use new headless mode
            
            # Additional Windows-specific fixes
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
            
            try:
                # Try to get ChromeDriver
                driver_path = ChromeDriverManager().install()
                logger.info(f"Using ChromeDriver at: {driver_path}")
                
                service = Service(driver_path)
                
                # Create driver with explicit timeout and error handling
                try:
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    self.driver.set_page_load_timeout(30)
                    self.driver.implicitly_wait(10)
                    
                    # Hide webdriver property
                    self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                    
                    logger.info("Chrome driver created successfully")
                    return self.driver
                except Exception as create_error:
                    error_msg = str(create_error)
                    logger.error(f"Error creating Chrome driver: {error_msg}")
                    
                    # Check if it's a known issue
                    if "devtools port" in error_msg.lower() or "json template" in error_msg.lower():
                        logger.info("Detected Chrome/ChromeDriver compatibility issue, trying simplified configuration...")
                        # Create new options without problematic settings
                        simple_options = Options()
                        simple_options.add_argument('--no-sandbox')
                        simple_options.add_argument('--disable-dev-shm-usage')
                        simple_options.add_argument('--disable-gpu')
                        if headless:
                            simple_options.add_argument('--headless=new')
                        
                        try:
                            self.driver = webdriver.Chrome(service=service, options=simple_options)
                            self.driver.set_page_load_timeout(30)
                            self.driver.implicitly_wait(10)
                            logger.info("Chrome driver created with simplified options")
                            return self.driver
                        except Exception as simple_error:
                            logger.error(f"Simplified options also failed: {str(simple_error)}")
                            raise Exception(f"Chrome driver creation failed. Please ensure Chrome browser is installed and up to date. Error: {error_msg}")
                    else:
                        raise
            except Exception as driver_error:
                error_msg = str(driver_error)
                logger.error(f"Error setting up Chrome driver: {error_msg}")
                
                # Provide helpful error message
                if "chromedriver" in error_msg.lower() or "driver" in error_msg.lower():
                    raise Exception(
                        f"Failed to create Chrome driver. "
                        f"Please ensure:\n"
                        f"1. Google Chrome browser is installed\n"
                        f"2. Chrome is up to date\n"
                        f"3. No other Chrome instances are blocking the driver\n"
                        f"Error: {error_msg}"
                    )
                else:
                    raise Exception(f"Failed to create browser driver: {error_msg}")
        except Exception as e:
            logger.error(f"Error creating Chrome driver: {str(e)}")
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            raise Exception(f"Failed to create browser driver: {str(e)}")
    
    async def _initialize_whatsapp_web(self):
        """Initialize WhatsApp Web connection"""
        try:
            if not self.driver:
                self._create_driver()
            
            if not self.driver:
                logger.error("Driver is None, cannot initialize WhatsApp Web")
                self.is_connected = False
                return False
            
            # Check if driver session is still valid
            try:
                _ = self.driver.current_url
            except Exception as session_error:
                logger.warning(f"Driver session invalid, recreating: {str(session_error)}")
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
                self._create_driver()
                if not self.driver:
                    self.is_connected = False
                    return False
            
            # Navigate to WhatsApp Web
            logger.info("Navigating to WhatsApp Web...")
            try:
                self.driver.get("https://web.whatsapp.com")
                await asyncio.sleep(3)  # Reduced wait time from 5 to 3 seconds
            except Exception as nav_error:
                logger.error(f"Error navigating to WhatsApp Web: {str(nav_error)}")
                # Try to recreate driver if navigation fails
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
                self.is_connected = False
                return False
            
            # Check if already logged in
            try:
                # Look for the main chat list (indicates logged in)
                # Try multiple selectors as WhatsApp may change them
                chat_list_selectors = [
                    "[data-testid='chat-list']",
                    "div[data-testid='chatlist']",
                    "#pane-side",
                    "div[role='grid']"
                ]
                
                found = False
                for selector in chat_list_selectors:
                    try:
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        found = True
                        break
                    except TimeoutException:
                        continue
                
                if found:
                    self.is_connected = True
                    logger.info("WhatsApp Web already connected")
                    return True
                else:
                    # Not logged in, need QR code
                    self.is_connected = False
                    logger.info("WhatsApp Web not connected, QR code required")
                    return False
            except Exception as check_error:
                logger.debug(f"Error checking connection status: {str(check_error)}")
                self.is_connected = False
                return False
        except Exception as e:
            logger.error(f"Error initializing WhatsApp Web: {str(e)}")
            self.is_connected = False
            # Don't quit driver here, let it be reused
            return False
    
    async def get_qr_code(self) -> Optional[str]:
        """
        Get QR code for WhatsApp Web authentication
        
        Returns:
            Base64 encoded QR code image or None
        """
        try:
            # Initialize WhatsApp Web if not already done
            if not self.driver:
                initialized = await self._initialize_whatsapp_web()
                if not initialized and not self.driver:
                    logger.error("Failed to initialize driver for QR code")
                    return None
            
            if not self.driver:
                logger.error("Driver is None, cannot get QR code")
                return None
            
            if self.is_connected:
                return None  # Already connected, no QR code needed
            
            # Wait for QR code to appear - try multiple selectors
            qr_selectors = [
                "canvas[aria-label*='Scan']",
                "canvas",
                "img[alt*='Scan']",
                "img[alt*='QR']",
                "div[data-ref] canvas",
                "div._2EZ_m canvas"
            ]
            
            qr_element = None
            for selector in qr_selectors:
                try:
                    qr_element = WebDriverWait(self.driver, 5).until(  # Reduced from 10 to 5 seconds
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if qr_element:
                        break
                except TimeoutException:
                    continue
            
            if not qr_element:
                logger.warning("QR code element not found")
                # Check if connected now (reduced wait time)
                await asyncio.sleep(1)  # Reduced from 2 to 1 second
                await self._initialize_whatsapp_web()
                if self.is_connected:
                    return None
                return None
            
            # Get QR code as base64
            try:
                qr_base64 = self.driver.execute_script("""
                    var element = arguments[0];
                    if (element.tagName === 'CANVAS') {
                        return element.toDataURL('image/png');
                    } else if (element.tagName === 'IMG') {
                        // For img elements, try to get src or create canvas
                        var canvas = document.createElement('canvas');
                        var ctx = canvas.getContext('2d');
                        canvas.width = element.naturalWidth || element.width;
                        canvas.height = element.naturalHeight || element.height;
                        ctx.drawImage(element, 0, 0);
                        return canvas.toDataURL('image/png');
                    } else {
                        return null;
                    }
                """, qr_element)
                
                if qr_base64:
                    # Remove data URL prefix if present
                    if qr_base64.startswith('data:image'):
                        qr_base64 = qr_base64.split(',')[1]
                    logger.info("QR code retrieved successfully")
                    return qr_base64
                else:
                    logger.warning("Could not extract QR code data")
                    return None
            except Exception as script_error:
                logger.error(f"Error executing QR code extraction script: {str(script_error)}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting QR code: {str(e)}")
            return None
    
    async def _fetch_messages_from_web(self, limit: int) -> List[WhatsAppMessage]:
        """Fetch messages from WhatsApp Web"""
        messages = []
        
        try:
            # Ensure driver exists and is valid
            if not self.driver:
                await self._initialize_whatsapp_web()
            
            if not self.driver:
                raise Exception("Failed to initialize browser. Please check if Chrome is installed and try again.")
            
            # Validate driver session
            try:
                _ = self.driver.current_url
            except Exception as session_error:
                logger.warning(f"Driver session lost, recreating: {str(session_error)}")
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
                self.is_connected = False
                await self._initialize_whatsapp_web()
                
                if not self.driver:
                    raise Exception("Failed to recreate browser driver. Please check if Chrome is installed and try again.")
            
            # Check connection status
            if not self.is_connected:
                # Try to initialize/check connection
                connected = await self._initialize_whatsapp_web()
                if not connected:
                    # Check if QR code is showing (not connected)
                    try:
                        # Look for QR code or login screen
                        qr_elements = self.driver.find_elements(By.CSS_SELECTOR, "canvas, div[data-ref], div._2EZ_m")
                        if qr_elements:
                            raise Exception("WhatsApp Web not connected. Please scan the QR code first. Click 'Refresh' to see the QR code.")
                        else:
                            raise Exception("WhatsApp Web connection status unknown. Please try scanning the QR code again.")
                    except Exception as qr_check:
                        raise qr_check
            
            # Wait for chat list to load - try multiple selectors with longer timeout
            chat_list_selectors = [
                "[data-testid='chat-list']",
                "div[data-testid='chatlist']",
                "#pane-side",
                "div[role='grid']",
                "div[aria-label*='Chat list']"
            ]
            
            chat_list_found = False
            for selector in chat_list_selectors:
                try:
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    chat_list_found = True
                    logger.info(f"Chat list found using selector: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not chat_list_found:
                # Check if we're still on the login page
                try:
                    login_indicators = self.driver.find_elements(By.CSS_SELECTOR, "canvas, div[data-ref], div._2EZ_m, div[aria-label*='QR']")
                    if login_indicators:
                        raise Exception("WhatsApp Web is not connected. Please scan the QR code first. The page may still be showing the login screen.")
                except Exception as login_check:
                    if "not connected" in str(login_check):
                        raise login_check
                
                # If we get here, the page loaded but chat list structure might be different
                raise Exception("Could not find chat list. WhatsApp Web may have changed its interface, or the page is still loading. Please try again.")
            
            # Get all chat items - try multiple selectors
            chat_items = []
            chat_selectors = [
                "[data-testid='chat-list'] > div > div",
                "#pane-side > div > div > div",
                "div[role='grid'] > div",
                "div[aria-label*='Chat list'] > div"
            ]
            
            for selector in chat_selectors:
                try:
                    chat_items = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if chat_items:
                        logger.info(f"Found chat items using selector: {selector}")
                        break
                except:
                    continue
            
            if not chat_items:
                logger.warning("No chat items found. WhatsApp may not be fully loaded or there are no chats.")
                # Return empty list instead of error - user might not have any chats
                return messages
            
            logger.info(f"Found {len(chat_items)} chats")
            
            # ULTRA-FAST METHOD: Extract preview messages first (instant), then open a few chats for full messages
            logger.info("Extracting messages using fast preview method...")
            
            # STEP 1: Extract preview messages from chat list (instant, no clicking needed)
            preview_extraction_script = """
            (function() {
                const previews = [];
                const chatItems = document.querySelectorAll('[data-testid="chat-list"] > div > div, #pane-side > div > div > div, div[role="grid"] > div');
                chatItems.forEach((item, idx) => {
                    try {
                        const nameElem = item.querySelector('span[title], span[dir="auto"]');
                        const name = nameElem ? (nameElem.getAttribute('title') || nameElem.textContent.trim()) : item.textContent.split('\\n')[0].trim();
                        if (!name || name === 'Unknown') return;
                        
                        const previewElem = item.querySelector('span[class*="selectable"], span[dir="ltr"], span[dir="auto"]');
                        const preview = previewElem ? previewElem.textContent.trim() : '';
                        const timeElem = item.querySelector('span[class*="time"], span[title]');
                        const time = timeElem ? (timeElem.getAttribute('title') || timeElem.textContent.trim()) : '';
                        
                        if (name && (preview || idx < 50)) {  // Get previews from up to 50 chats
                            previews.push({
                                index: idx,
                                chatName: name,
                                body: preview || '[Chat exists]',
                                timestamp: time || new Date().toLocaleString(),
                                isSent: false
                            });
                        }
                    } catch (e) {}
                });
                return previews;
            })();
            """
            
            try:
                # First, get all preview messages instantly (no clicking)
                preview_messages = self.driver.execute_script(preview_extraction_script)
                logger.info(f"Extracted {len(preview_messages)} preview messages from chat list")
                
                # Convert previews to WhatsAppMessage objects
                for prev in preview_messages:
                    if limit > 0 and len(messages) >= limit:
                        break
                    chat_name = prev.get('chatName', 'Unknown')
                    body = prev.get('body', '[Preview]')
                    timestamp = prev.get('timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    message = WhatsAppMessage(
                        message_id=f"preview_{abs(hash(f'{chat_name}_{body}_{timestamp}'))}",
                        from_number=chat_name,
                        from_name=chat_name,
                        body=body,
                        timestamp=timestamp,
                        is_read=True,
                        chat_id=chat_name,
                        chat_name=chat_name
                    )
                    messages.append(message)
                
                logger.info(f"Added {len(preview_messages)} preview messages")
                
                # If we have enough preview messages, return them immediately (fast!)
                if len(messages) >= 20:  # If we have 20+ preview messages, return immediately
                    logger.info(f"Returning {len(messages)} preview messages immediately (fast path)")
                    return messages
                
                # STEP 2: Only open top 3 chats for full message extraction (very limited for speed)
                max_chats_to_open = min(3, len(preview_messages))  # Only open top 3 chats for speed
                logger.info(f"Opening {max_chats_to_open} chats for full message extraction")
                
                processed_chats = 0
                for chat_data in preview_messages[:max_chats_to_open]:
                    if limit > 0 and len(messages) >= limit:
                        break
                    
                    chat_name = chat_data.get('chatName', 'Unknown')
                    chat_index = chat_data.get('index', 0)
                    
                    if chat_name == 'Unknown':
                        continue  # Skip unknown chats
                    
                    try:
                        # Use JavaScript to open chat and extract all messages in one go
                        extract_all_messages_script = f"""
                        (function() {{
                            try {{
                                const chatItems = document.querySelectorAll('[data-testid="chat-list"] > div > div, #pane-side > div > div > div, div[role="grid"] > div');
                                const targetChat = chatItems[{chat_index}];
                                if (!targetChat) return [];
                                
                                // Click to open chat
                                targetChat.click();
                                
                                // Wait for messages to load (minimal wait)
                                const startTime = Date.now();
                                while (Date.now() - startTime < 150) {{
                                    // Wait 150ms for messages to load (reduced for speed)
                                }}
                                
                                // Extract all visible messages
                                const allMessages = [];
                                const msgContainers = document.querySelectorAll('[data-testid="msg-container"], div[data-testid="conversation-panel-messages"] > div > div, div[role="application"] > div > div');
                                
                                msgContainers.forEach((container, idx) => {{
                                    try {{
                                        let body = '';
                                        let timestamp = '';
                                        let isSent = false;
                                        
                                        // Get text - try multiple selectors
                                        const textElem = container.querySelector('span.selectable-text, span[class*="selectable"], span[dir="ltr"], span[dir="auto"], div[class*="text"]');
                                        if (textElem) {{
                                            body = textElem.textContent.trim();
                                        }}
                                        
                                        // If no text, try getting all text from container
                                        if (!body || body.length < 2) {{
                                            const allText = container.textContent.trim();
                                            if (allText && allText.length > 2) {{
                                                body = allText.substring(0, 200);
                                            }}
                                        }}
                                        
                                        // Check for media
                                        if (!body || body.length < 2) {{
                                            const media = container.querySelector('img, video, audio');
                                            if (media) {{
                                                body = '[Media]';
                                            }}
                                        }}
                                        
                                        // Get timestamp
                                        const timeElem = container.querySelector('span[data-testid="msg-meta"], span[class*="time"]');
                                        if (timeElem) {{
                                            timestamp = timeElem.getAttribute('title') || timeElem.textContent.trim() || '';
                                        }}
                                        
                                        // Check if sent
                                        const className = container.className || '';
                                        isSent = className.includes('message-out') || className.includes('sent') || className.includes('outgoing');
                                        
                                        // Only add if we have meaningful content
                                        if (body && body.length > 0) {{
                                            allMessages.push({{
                                                body: body,
                                                timestamp: timestamp || new Date().toLocaleString(),
                                                isSent: isSent
                                            }});
                                        }}
                                    }} catch (e) {{
                                        // Skip errors
                                    }}
                                }});
                                
                                // Go back to chat list
                                const backBtn = document.querySelector('[data-testid="back"]');
                                if (backBtn) {{
                                    backBtn.click();
                                    // Small wait after going back
                                    const backTime = Date.now();
                                    while (Date.now() - backTime < 100) {{
                                        // Wait 100ms
                                    }}
                                }}
                                
                                return allMessages;
                            }} catch (e) {{
                                return [];
                            }}
                        }})();
                        """
                        
                        # Execute extraction
                        chat_messages = self.driver.execute_script(extract_all_messages_script)
                        
                        if chat_messages and len(chat_messages) > 0:
                            # Add all messages from this chat
                            for msg_data in chat_messages:
                                if limit > 0 and len(messages) >= limit:
                                    break
                                
                                from_name = "You" if msg_data.get('isSent') else chat_name
                                body_text = msg_data.get('body', '[Message]')
                                timestamp_text = msg_data.get('timestamp', '')
                                
                                # Only add if body has content
                                if body_text and body_text.strip():
                                    message = WhatsAppMessage(
                                        message_id=f"fast_{abs(hash(f'{chat_name}_{body_text}_{timestamp_text}_{len(messages)}'))}",
                                        from_number=chat_name,
                                        from_name=from_name,
                                        body=body_text,
                                        timestamp=timestamp_text or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        is_read=True,
                                        chat_id=chat_name,
                                        chat_name=chat_name
                                    )
                                    messages.append(message)
                            
                            processed_chats += 1
                            logger.info(f"Extracted {len(chat_messages)} messages from {chat_name} (Total: {len(messages)}, Processed: {processed_chats}/{max_chats_to_process})")
                            
                            # Early return if we have enough messages (for speed)
                            if len(messages) >= 20:  # If we have 20+ messages, return early
                                logger.info(f"Have {len(messages)} messages, returning early for speed")
                                return messages
                        else:
                            logger.debug(f"No messages extracted from {chat_name}")
                        
                        # Small delay to prevent overwhelming the browser (minimal)
                        await asyncio.sleep(0.03)  # Reduced to 0.03 for speed
                        
                    except Exception as chat_error:
                        logger.warning(f"Error processing chat {chat_name}: {str(chat_error)}")
                        continue
                
                logger.info(f"Fast extraction complete: {len(messages)} messages ({len(preview_messages)} previews + {processed_chats} full chats)")
                
                # If we got messages, return them immediately
                if messages and len(messages) > 0:
                    logger.info(f"Returning {len(messages)} messages (previews + full messages from {processed_chats} chats)")
                    return messages
                else:
                    logger.warning("Fast extraction returned no messages, trying fallback method")
                    raise Exception("No messages extracted")
                    
            except Exception as js_error:
                logger.warning(f"Ultra-fast extraction failed: {str(js_error)}, falling back to optimized method")
            
            # FALLBACK: If fast method fails, use the slower method but optimized
            logger.info("Using optimized slow method (fallback)...")
            processed_count = 0
            max_chats_to_process = len(chat_items) if limit <= 0 or limit >= 50 else min(limit, len(chat_items))
            
            logger.info(f"Processing {max_chats_to_process} chats (fallback method)")
            
            for chat_item in chat_items[:max_chats_to_process]:
                if limit > 0 and len(messages) >= limit:
                    logger.info(f"Reached message limit of {limit}, stopping")
                    break
                try:
                    # Click on chat to open it
                    try:
                        chat_item.click()
                    except Exception as click_error:
                        # Try JavaScript click as fallback
                        try:
                            self.driver.execute_script("arguments[0].click();", chat_item)
                        except:
                            logger.warning(f"Could not click chat item: {str(click_error)}")
                            continue
                    
                    # Minimal wait for chat to open (optimized for speed)
                    await asyncio.sleep(0.1)  # Reduced from 0.5 to 0.1
                    
                    # Quick check for message area (reduced timeout)
                    try:
                        WebDriverWait(self.driver, 1).until(  # Reduced from 3 to 1
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='application'], div[data-testid='conversation-panel-messages'], #main"))
                        )
                    except TimeoutException:
                        logger.debug("Message area not found quickly, continuing anyway")
                    
                    # Get chat name - try multiple selectors
                    chat_name = "Unknown"
                    chat_name_selectors = [
                        "[data-testid='conversation-header'] span[title]",
                        "[data-testid='conversation-header'] span",
                        "header span[title]",
                        "div[role='banner'] span[title]"
                    ]
                    for selector in chat_name_selectors:
                        try:
                            chat_name_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                            chat_name = chat_name_element.get_attribute('title') or chat_name_element.text
                            if chat_name and chat_name != "Unknown":
                                break
                        except:
                            continue
                    
                    if chat_name == "Unknown":
                        # Try to get from chat item itself
                        try:
                            chat_name = chat_item.text.split('\n')[0] if chat_item.text else "Unknown"
                        except:
                            pass
                    
                    logger.info(f"Processing chat: {chat_name}")
                    
                    # FAST: Use JavaScript to extract all visible messages at once
                    try:
                        extract_messages_script = """
                        (function() {
                            const msgs = [];
                            const containers = document.querySelectorAll('[data-testid="msg-container"], div[data-testid="conversation-panel-messages"] > div > div, div[role="application"] > div > div');
                            
                            containers.forEach((container, idx) => {
                                try {
                                    let body = '';
                                    let timestamp = '';
                                    let isSent = false;
                                    
                                    // Get text
                                    const textElem = container.querySelector('span.selectable-text, span[class*="selectable"], span[dir="ltr"], span[dir="auto"]');
                                    if (textElem) {
                                        body = textElem.textContent.trim();
                                    }
                                    
                                    // Check for media
                                    if (!body) {
                                        const media = container.querySelector('img, video, audio');
                                        if (media) {
                                            body = '[Media]';
                                        }
                                    }
                                    
                                    // Get timestamp
                                    const timeElem = container.querySelector('span[data-testid="msg-meta"]');
                                    if (timeElem) {
                                        timestamp = timeElem.getAttribute('title') || timeElem.textContent.trim() || '';
                                    }
                                    
                                    // Check if sent
                                    const className = container.className || '';
                                    isSent = className.includes('message-out') || className.includes('sent') || className.includes('outgoing');
                                    
                                    if (body || idx < 5) {  // Include first few even if empty
                                        msgs.push({
                                            body: body || '[Message]',
                                            timestamp: timestamp || new Date().toLocaleString(),
                                            isSent: isSent
                                        });
                                    }
                                } catch (e) {}
                            });
                            
                            return msgs;
                        })();
                        """
                        js_messages = self.driver.execute_script(extract_messages_script)
                        
                        if js_messages and len(js_messages) > 0:
                            # Process JavaScript-extracted messages (much faster)
                            for js_msg in js_messages[:50]:  # Limit to 50 per chat for speed
                                if limit > 0 and len(messages) >= limit:
                                    break
                                
                                from_name = "You" if js_msg.get('isSent') else chat_name
                                body_text = js_msg.get('body', '[Message]')
                                timestamp_text = js_msg.get('timestamp', '')
                                message = WhatsAppMessage(
                                    message_id=f"js_{abs(hash(f'{chat_name}_{body_text}_{timestamp_text}'))}",
                                    from_number=chat_name,
                                    from_name=from_name,
                                    body=body_text,
                                    timestamp=timestamp_text or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    is_read=True,
                                    chat_id=chat_name,
                                    chat_name=chat_name
                                )
                                messages.append(message)
                            
                            processed_count += 1
                            logger.info(f"Extracted {len(js_messages)} messages from {chat_name} via JS (Total: {len(messages)})")
                            
                            # Go back quickly
                            try:
                                self.driver.execute_script("document.querySelector('[data-testid=\"back\"]')?.click() || document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
                                await asyncio.sleep(0.05)  # Minimal wait
                            except:
                                pass
                            
                            if limit > 0 and len(messages) >= limit:
                                break
                            continue
                    except Exception as js_extract_error:
                        logger.debug(f"JS extraction failed for {chat_name}, using fallback: {str(js_extract_error)}")
                    
                    # FALLBACK: Traditional method (slower)
                    message_elements = []
                    message_selectors = [
                        "[data-testid='msg-container']",
                        "div[data-testid='conversation-panel-messages'] > div > div",
                        "div[role='application'] > div > div"
                    ]
                    
                    for selector in message_selectors[:2]:  # Only try first 2 selectors for speed
                        try:
                            message_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if message_elements:
                                break
                        except:
                            continue
                    
                    if not message_elements:
                        logger.warning(f"No messages found in chat: {chat_name}")
                        # Still create a placeholder message to show the chat exists
                        message = WhatsAppMessage(
                            message_id=f"web_chat_{hash(chat_name)}",
                            from_number=chat_name,
                            from_name=chat_name,
                            body="[No messages found or chat is empty]",
                            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            is_read=True,
                            chat_id=chat_name,
                            chat_name=chat_name
                        )
                        messages.append(message)
                        processed_count += 1
                        continue
                    
                    # Process messages using Selenium (reliable fallback)
                    message_count = 0
                    messages_to_process = message_elements[-50:] if len(message_elements) > 50 else message_elements  # Get last 50 for better coverage
                    
                    logger.info(f"Processing {len(messages_to_process)} message elements from {chat_name} (fallback)")
                    
                    for idx, msg_elem in enumerate(messages_to_process):
                        if limit > 0 and len(messages) >= limit:
                            break
                        try:
                            # Try to get text content
                            body = ""
                            try:
                                # Try selectable text first
                                text_elem = msg_elem.find_element(By.CSS_SELECTOR, "span.selectable-text, span[class*='selectable']")
                                body = text_elem.text.strip()
                            except:
                                # Fallback to element text
                                try:
                                    body = msg_elem.text.strip()
                                    # Clean up - remove timestamps and other metadata
                                    if body:
                                        lines = body.split('\n')
                                        # Take first meaningful line
                                        for line in lines:
                                            if line.strip() and len(line.strip()) > 2:
                                                body = line.strip()
                                                break
                                except:
                                    body = ""
                            
                            # If still no body, check for media
                            if not body or len(body) < 2:
                                try:
                                    media = msg_elem.find_elements(By.CSS_SELECTOR, "img, video, audio")
                                    if media:
                                        body = "[Media]"
                                    else:
                                        # Skip empty messages
                                        continue
                                except:
                                    continue
                            
                            # Get timestamp
                            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                time_elem = msg_elem.find_element(By.CSS_SELECTOR, "span[data-testid='msg-meta']")
                                time_text = time_elem.get_attribute('title') or time_elem.text
                                if time_text:
                                    timestamp_str = time_text
                            except:
                                pass
                            
                            # Check if sent
                            is_sent = False
                            try:
                                msg_class = msg_elem.get_attribute("class") or ""
                                is_sent = "message-out" in msg_class or "sent" in msg_class.lower()
                            except:
                                pass
                            
                            from_name = "You" if is_sent else chat_name
                            
                            message = WhatsAppMessage(
                                message_id=f"fallback_{abs(hash(f'{chat_name}_{body}_{idx}_{len(messages)}'))}",
                                from_number=chat_name,
                                from_name=from_name,
                                body=body[:500],  # Limit to 500 chars
                                timestamp=timestamp_str,
                                is_read=True,
                                chat_id=chat_name,
                                chat_name=chat_name
                            )
                            messages.append(message)
                            message_count += 1
                        except Exception as msg_error:
                            logger.debug(f"Error parsing message {idx}: {str(msg_error)}")
                            continue
                    
                    logger.info(f"Extracted {message_count} messages from {chat_name} via fallback (Total: {len(messages)})")
                    
                    processed_count += 1
                    logger.info(f"Extracted {message_count} messages from {chat_name} (Total so far: {len(messages)})")
                    
                    # Check if we've reached the message limit
                    if limit > 0 and len(messages) >= limit:
                        logger.info(f"Reached message limit of {limit}, stopping chat processing")
                        break
                    
                    # Quick navigation back (already handled in JS extraction, but keep for fallback)
                    if message_count > 0:  # Only if we processed messages
                        try:
                            self.driver.execute_script("document.querySelector('[data-testid=\"back\"]')?.click()")
                            await asyncio.sleep(0.05)  # Minimal wait
                        except:
                            pass
                        
                except Exception as chat_error:
                    logger.warning(f"Error processing chat: {str(chat_error)}")
                    # Try to go back to chat list even on error
                    try:
                        from selenium.webdriver.common.keys import Keys
                        self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        await asyncio.sleep(0.1)
                    except:
                        pass
                    continue
            
            logger.info(f"Total messages extracted: {len(messages)} from {processed_count} chats")
            
            # Return all collected messages
            if messages and len(messages) > 0:
                logger.info(f"Returning {len(messages)} WhatsApp messages (processed {processed_count} chats)")
                return messages
            else:
                # Last resort: Try to get at least preview messages from chat list
                logger.warning("No messages extracted, trying last resort: chat list previews")
                try:
                    # Get chat list items and extract preview messages
                    chat_list_preview_script = """
                    (function() {
                        const previews = [];
                        const chatItems = document.querySelectorAll('[data-testid="chat-list"] > div > div, #pane-side > div > div > div');
                        chatItems.forEach((item, idx) => {
                            try {
                                const nameElem = item.querySelector('span[title], span[dir="auto"]');
                                const name = nameElem ? (nameElem.getAttribute('title') || nameElem.textContent.trim()) : item.textContent.split('\\n')[0].trim();
                                const previewElem = item.querySelector('span[class*="selectable"], span[dir="ltr"], span[dir="auto"]');
                                const preview = previewElem ? previewElem.textContent.trim() : '';
                                const timeElem = item.querySelector('span[class*="time"]');
                                const time = timeElem ? (timeElem.getAttribute('title') || timeElem.textContent.trim()) : '';
                                
                                if (name && name !== 'Unknown' && (preview || idx < 10)) {
                                    previews.push({
                                        chatName: name,
                                        body: preview || '[Chat exists]',
                                        timestamp: time || new Date().toLocaleString(),
                                        isSent: false
                                    });
                                }
                            } catch (e) {}
                        });
                        return previews;
                    })();
                    """
                    previews = self.driver.execute_script(chat_list_preview_script)
                    if previews and len(previews) > 0:
                        for prev in previews:
                            chat_name = prev.get('chatName', 'Unknown')
                            body = prev.get('body', '[Preview]')
                            timestamp = prev.get('timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            message = WhatsAppMessage(
                                message_id=f"preview_{abs(hash(f'{chat_name}_{body}_{timestamp}'))}",
                                from_number=chat_name,
                                from_name=chat_name,
                                body=body,
                                timestamp=timestamp,
                                is_read=True,
                                chat_id=chat_name,
                                chat_name=chat_name
                            )
                            messages.append(message)
                        logger.info(f"Got {len(previews)} preview messages as last resort")
                        return messages
                except Exception as preview_error:
                    logger.error(f"Last resort preview extraction also failed: {str(preview_error)}")
                
                # If we still have no messages, return empty list
                logger.error("Failed to extract any WhatsApp messages. Please check logs for details.")
                return messages
            
            if not messages:
                logger.warning("No messages extracted from any chats. This might mean:")
                logger.warning("1. WhatsApp Web is not fully connected")
                logger.warning("2. There are no chats with messages")
                logger.warning("3. The page structure has changed")
                logger.warning("4. Message parsing failed for all chats")
            
            return messages
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching messages from WhatsApp Web: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            
            # If we have some messages, return them even if there was an error
            if messages:
                logger.warning(f"Returning {len(messages)} messages despite error")
                return messages
            
            # Re-raise with more context
            if "not connected" in error_msg.lower():
                raise Exception("WhatsApp Web is not connected. Please scan the QR code first.")
            elif "timeout" in error_msg.lower():
                raise Exception("Timeout waiting for WhatsApp Web. Please make sure it's connected and try again.")
            else:
                raise Exception(f"Error extracting messages from WhatsApp Web: {error_msg}")
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check if WhatsApp is connected (Cloud API or Web)
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        # Check Cloud API first
        if self.use_cloud_api:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}"
                    headers = {
                        'Authorization': f'Bearer {self.access_token}'
                    }
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            return True, "Connected to WhatsApp Cloud API"
                        else:
                            error_text = await response.text()
                            # Try to parse error for better message
                            try:
                                error_data = await response.json()
                                error_detail = error_data.get('error', {})
                                error_message = error_detail.get('message', error_text)
                                error_code = error_detail.get('code', '')
                                if error_code == 2190 or "OAuth" in error_message or "access token" in error_message.lower():
                                    return False, f"Cloud API authentication failed: Invalid or expired access token. Please update WHATSAPP_ACCESS_TOKEN in .env or remove it to use WhatsApp Web."
                                else:
                                    return False, f"Cloud API connection failed: {error_message}"
                            except:
                                return False, f"Cloud API connection failed: {error_text}. Please check your WHATSAPP_ACCESS_TOKEN or remove it to use WhatsApp Web."
            except Exception as e:
                error_msg = str(e)
                if "OAuth" in error_msg or "access token" in error_msg.lower():
                    return False, f"Cloud API authentication error: {error_msg}. Please update WHATSAPP_ACCESS_TOKEN in .env or remove it to use WhatsApp Web."
                return False, f"Error checking Cloud API connection: {error_msg}"
        
        # Check WhatsApp Web
        try:
            if not self.driver:
                await self._initialize_whatsapp_web()
            
            if self.is_connected:
                return True, "Connected to WhatsApp Web"
            else:
                return False, "WhatsApp Web not connected. Please scan QR code."
        except Exception as e:
            return False, f"Error checking WhatsApp Web connection: {str(e)}"
