"""
Application Launcher Service
Handles launching applications on the system
"""

import os
import sys
import subprocess
import logging
import platform
from typing import Optional, List

logger = logging.getLogger(__name__)


class AppLauncher:
    """Service for launching applications"""
    
    def __init__(self):
        self.os_type = platform.system()
        self._app_cache = {}  # Cache resolved app paths for faster launches
        logger.info(f"App Launcher initialized for {self.os_type}")
    
    async def launch_app(
        self,
        app_name: str,
        args: Optional[List[str]] = None
    ) -> bool:
        """
        Launch an application
        
        Args:
            app_name: Name or path of the application
            args: Optional command-line arguments
        
        Returns:
            True if app was launched successfully
        """
        try:
            command = self._build_command(app_name, args)
            
            logger.info(f"Launching: {' '.join(command)}")
            
            if self.os_type == "Windows":
                # Use os.startfile for simpler Windows app launching
                # This handles both classic apps and protocol handlers like telegram:, whatsapp:
                if command[0].endswith(':'):
                    # Protocol handler - use os.startfile
                    try:
                        os.startfile(command[0])
                    except Exception as e:
                        logger.warning(f"Protocol handler failed {command[0]}: {e}, trying Start-Process")
                        # Fallback to Start-Process
                        ps_command = f'Start-Process "{command[0]}"'
                        subprocess.Popen(
                            ['powershell.exe', '-NoProfile', '-Command', ps_command],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                else:
                    # Regular executable - use Start-Process for better compatibility
                    ps_command = f'Start-Process "{command[0]}"'
                    if len(command) > 1:
                        args_str = ' '.join(f'"{arg}"' for arg in command[1:])
                        ps_command = f'Start-Process "{command[0]}" -ArgumentList @({args_str})'
                    
                    subprocess.Popen(
                        ['powershell.exe', '-NoProfile', '-Command', ps_command],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
            else:
                # Unix-like systems
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            logger.info(f"Successfully launched: {app_name}")
            return True
        
        except FileNotFoundError:
            logger.error(f"Application not found: {app_name}")
            return False
        except Exception as e:
            logger.error(f"Error launching app: {str(e)}")
            raise
    
    def _build_command(self, app_name: str, args: Optional[List[str]] = None) -> List[str]:
        """Build the command to launch the app"""
        args = args or []
        app_name = app_name.strip()  # Clean whitespace
        
        if self.os_type == "Windows":
            # Windows application launching
            if os.path.exists(app_name):
                # Full path provided
                return [app_name] + args
            else:
                # Try common locations and app names (first exact, then variations)
                common_apps = self._get_windows_app_path(app_name)
                if common_apps:
                    if isinstance(common_apps, tuple):
                        return list(common_apps) + args
                    return [common_apps] + args
                else:
                    # Try variations: replace spaces with nothing, or try each word
                    # e.g., "task manager" -> "taskmanager"
                    app_no_space = app_name.replace(' ', '')
                    if app_no_space != app_name:
                        common_apps = self._get_windows_app_path(app_no_space)
                        if common_apps:
                            if isinstance(common_apps, tuple):
                                return list(common_apps) + args
                            return [common_apps] + args
                    # Last resort: try as command
                    return [app_name] + args
        
        elif self.os_type == "Darwin":
            # macOS
            if app_name.endswith('.app'):
                return ["open", "-a", app_name] + args
            else:
                return ["open", "-a", app_name] + args
        
        else:
            # Linux and other Unix-like systems
            return [app_name] + args
    
    def _get_windows_app_path(self, app_name: str) -> Optional[str]:
        """Get Windows application path from common locations"""
        import glob
        import winreg
        
        app_name_lower = app_name.lower()
        
        # Check cache first for faster lookups
        if app_name_lower in self._app_cache:
            cached_path = self._app_cache[app_name_lower]
            if cached_path and isinstance(cached_path, str) and os.path.exists(cached_path):
                return cached_path
            elif cached_path and isinstance(cached_path, str) and ':' in cached_path:
                # Protocol handler - always valid
                return cached_path
        
        # Common application mappings
        app_mappings = {
            'notepad': 'notepad.exe',
            # Calculator variants (classic exe and UWP protocol)
            'calculator': r'C:\Windows\System32\calc.exe',
            'calc': r'C:\Windows\System32\calc.exe',
            'ms-calculator': 'ms-calculator:',
            'calculator_app': 'calculator:',
            'paint': 'mspaint.exe',
            'chrome': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            'firefox': r'C:\Program Files\Mozilla Firefox\firefox.exe',
            'edge': r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            'vscode': r'C:\Program Files\Microsoft VS Code\Code.exe',
            'code': r'C:\Program Files\Microsoft VS Code\Code.exe',
            'excel': r'C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE',
            'word': r'C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE',
            'powerpoint': r'C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE',
            'outlook': r'C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE',
            # Messaging apps - WindowsApps versions
            'telegram': os.path.join(os.environ.get('LOCALAPPDATA', ''), r'Microsoft\WindowsApps\Telegram.exe'),
            'unigram': os.path.join(os.environ.get('LOCALAPPDATA', ''), r'Microsoft\WindowsApps\38833FF26BA1D.UnigramPreview_g9c9v27vpyspw\Telegram.exe'),
            'whatsapp': 'whatsapp:',  # Try protocol handler first
            'discord': None,  # Handle separately with dynamic search
            'zoom': 'zoommtg:',
            'spotify': 'spotify:',
            'vlc': r'C:\Program Files\VideoLAN\VLC\vlc.exe',
            # Windows inbox apps (UWP)
            'clock': 'ms-clock:',
            'alarm': 'ms-clock:',
            'alarms': 'ms-clock:',
            'sticky': ('explorer.exe', r'shell:appsFolder\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App'),
            'stickies': ('explorer.exe', r'shell:appsFolder\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App'),
            'sticky notes': ('explorer.exe', r'shell:appsFolder\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App'),
            'stickynotes': ('explorer.exe', r'shell:appsFolder\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App'),
            # System apps
            'explorer': 'explorer.exe',
            'cmd': 'cmd.exe',
            'command': 'cmd.exe',
            'powershell': 'powershell.exe',
            'shell': 'powershell.exe',
            'task manager': r'C:\Windows\System32\Taskmgr.exe',
            'taskmanager': r'C:\Windows\System32\Taskmgr.exe',
            'taskmgr': r'C:\Windows\System32\Taskmgr.exe',
            'tm': r'C:\Windows\System32\Taskmgr.exe',
            'tasks': r'C:\Windows\System32\Taskmgr.exe',
            'control panel': 'control.exe',
            'control': 'control.exe',
        }
        
        # Special handling for Discord
        if app_name_lower == 'discord':
            discord_base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Discord')
            if os.path.exists(discord_base):
                discord_apps = glob.glob(os.path.join(discord_base, 'app-*', 'Discord.exe'))
                if discord_apps:
                    return max(discord_apps, key=os.path.getmtime)
            # Fallback to discord: protocol
            return 'discord:'
        
        # Check if app name is in mappings
        if app_name_lower in app_mappings:
            app_path = app_mappings[app_name_lower]
            if app_path is None:
                return None
            if isinstance(app_path, tuple):
                self._app_cache[app_name_lower] = app_path
                return app_path
            # Protocol handlers or already resolved
            if ':' in app_path:
                self._app_cache[app_name_lower] = app_path
                return app_path
            # Check if path exists
            if os.path.exists(app_path):
                self._app_cache[app_name_lower] = app_path
                return app_path
            logger.warning(f"Mapped path not found: {app_path}")
        
        # Try to find in Windows registry (App Paths)
        try:
            reg_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                try:
                    with winreg.OpenKey(key, f'{app_name}.exe') as subkey:
                        app_path, _ = winreg.QueryValueEx(subkey, '')
                        if os.path.exists(app_path):
                            logger.info(f"Found {app_name} in registry: {app_path}")
                            self._app_cache[app_name_lower] = app_path
                            return app_path
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.debug(f"Registry lookup failed for {app_name}: {e}")
        
        # Try common program files
        program_files = [
            os.environ.get('ProgramFiles', r'C:\Program Files'),
            os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
            os.environ.get('LOCALAPPDATA', ''),
        ]
        
        for pf_dir in program_files:
            if not pf_dir:
                continue
            # Try appname\appname.exe pattern
            possible_path = os.path.join(pf_dir, app_name, f"{app_name}.exe")
            if os.path.exists(possible_path):
                self._app_cache[app_name_lower] = possible_path
                return possible_path
            # Try just appname.exe
            possible_path = os.path.join(pf_dir, f"{app_name}.exe")
            if os.path.exists(possible_path):
                self._app_cache[app_name_lower] = possible_path
                return possible_path
        
        # Last resort: return the app name and let Windows search for it
        return app_name_lower
