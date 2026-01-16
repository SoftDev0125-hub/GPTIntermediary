"""
Application Launcher Service
Handles launching applications on the system
"""

import os
import sys
import subprocess
import logging
import platform
import shutil
from typing import Optional, List
import json
import urllib.request
import urllib.error

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

            # Validate the command/executable exists before attempting to start it.
            exe = command[0]
            resolved_exe = shutil.which(exe) if not os.path.isabs(exe) else (exe if os.path.exists(exe) else None)
            if resolved_exe is None:
                logger.error(f"Executable not found on PATH: {exe}")
                return False

            if self.os_type == "Windows":
                # If running inside the Services session, try forwarding the launch
                # to a small agent running in the interactive user session.
                try:
                    session_name = os.environ.get('SESSIONNAME', '').lower()
                except Exception:
                    session_name = ''

                if session_name == 'services':
                    try:
                        port = os.environ.get('LAUNCH_AGENT_PORT', '5001')
                        secret = os.environ.get('LAUNCH_AGENT_SECRET', '')
                        url = f'http://127.0.0.1:{port}/launch'
                        payload = json.dumps({'app': app_name, 'args': args}).encode('utf-8')
                        req = urllib.request.Request(url, data=payload, headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {secret}'
                        })
                        with urllib.request.urlopen(req, timeout=2) as resp:
                            if resp.getcode() == 200:
                                logger.info(f'Forwarded launch to desktop agent: {app_name}')
                                return True
                    except Exception as e:
                        logger.debug(f'Desktop agent not available or failed: {e}')
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
                        logger.info(f"Successfully launched protocol handler: {app_name}")
                        return True
                else:
                    # Regular executable - prefer os.startfile to open in interactive session
                    target = resolved_exe or command[0]
                    try:
                        os.startfile(target)
                        logger.info(f"Successfully launched: {app_name}")
                        return True
                    except Exception as e:
                        logger.warning(f"os.startfile failed for {target}: {e}, falling back to Start-Process")
                        # Fallback to Start-Process for broader compatibility
                        ps_target = resolved_exe or command[0]
                        ps_command = f'Start-Process "{ps_target}"'
                        if len(command) > 1:
                            args_str = ' '.join(f'"{arg}"' for arg in command[1:])
                            ps_command = f'Start-Process "{ps_target}" -ArgumentList @({args_str})'

                        subprocess.Popen(
                            ['powershell.exe', '-NoProfile', '-Command', ps_command],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        logger.info(f"Successfully launched via Start-Process: {app_name}")
                        return True
            else:
                # Unix-like systems
                try:
                    # Ensure child inherits current environment (incl. DISPLAY when set)
                    env = os.environ.copy()
                    subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        env=env,
                    )
                    logger.info(f"Successfully launched: {app_name}")
                    return True
                except FileNotFoundError:
                    logger.error(f"Application not found: {app_name}")
                    return False
                except Exception as e:
                    logger.error(f"Error launching app: {str(e)}")
                    return False

        except FileNotFoundError:
            logger.error(f"Application not found: {app_name}")
            return False
        except Exception as e:
            logger.error(f"Error preparing launch: {str(e)}")
            return False
    
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
                app_name_lower = app_name.lower()

                # Detect headless (no X/Wayland display). If headless, GUI openers won't work.
                headless = not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_SESSION_TYPE'))

                # Map common Windows app names to Linux equivalents (try the first available)
                windows_aliases = {
                    'notepad': ['nano', 'gedit', 'xed', 'mousepad'],
                    'explorer': ['nautilus', 'thunar', 'pcmanfm'],
                    'calculator': ['gnome-calculator', 'galculator', 'xcalc', 'bc'],
                    'paint': ['gimp', 'pinta'],
                    'word': ['libreoffice', 'libreoffice --writer'],
                    'excel': ['libreoffice', 'libreoffice --calc'],
                }

                # Common Linux mappings for friendly aliases (try the first available)
                linux_mappings = {
                    'calculator': ['gnome-calculator', 'galculator', 'xcalc', 'bc'],
                    'calc': ['gnome-calculator', 'galculator', 'xcalc', 'bc'],
                    'chrome': ['google-chrome', 'chrome', 'chromium', 'chromium-browser'],
                    'firefox': ['firefox'],
                    'vlc': ['vlc'],
                    'code': ['code', 'code-oss'],
                    'telegram': ['telegram-desktop'],
                    'discord': ['discord']
                }

                # If user provided a friendly alias, try mapped executables first
                if app_name_lower in linux_mappings:
                    for candidate in linux_mappings[app_name_lower]:
                        path = shutil.which(candidate.split()[0])
                        if path:
                            return [path] + args

                # Try Windows alias mappings (e.g., user says 'notepad')
                if app_name_lower in windows_aliases:
                    for candidate in windows_aliases[app_name_lower]:
                        # candidate may include spaces (e.g., 'libreoffice --writer')
                        parts = candidate.split()
                        exe = parts[0]
                        path = shutil.which(exe)
                        if path:
                            # If headless and candidate is a GUI app, try to run with xvfb-run if available
                            if headless and exe not in ['nano', 'vi', 'vim', 'bc', 'cat']:
                                xvfb = shutil.which('xvfb-run')
                                if xvfb:
                                    extra = parts[1:] if len(parts) > 1 else []
                                    return [xvfb, '-a', path] + extra + args
                                else:
                                    logger.warning(f"Headless environment and no xvfb-run; launching {exe} may not show a display")
                            extra = parts[1:] if len(parts) > 1 else []
                            return [path] + extra + args

                # If the name itself is on PATH, use it
                path = shutil.which(app_name)
                if path:
                    return [path] + args

                # If the target looks like a URL, protocol handler, or an existing file,
                # prefer the desktop opener (xdg-open, gio, sensible-browser) so it
                # works for URLs and protocol handlers on Unix systems.
                try:
                    looks_like_url = ('://' in app_name) or app_name.startswith('www.')
                except Exception:
                    looks_like_url = False

                if os.path.exists(app_name) or looks_like_url or (':' in app_name and not app_name.startswith('/')):
                    opener = shutil.which('xdg-open') or shutil.which('gio') or shutil.which('sensible-browser')
                    if opener:
                        if headless:
                            # In headless VPS, attempting to run a GUI opener will fail silently.
                            logger.warning(f"Headless environment detected; cannot open GUI target: {app_name}")
                            # Return the opener command so logs show intent, but raising FileNotFoundError
                            # later will convert to a 404 response. Alternatively, return the opener
                            # to attempt it anyway: return [opener, app_name] + args
                            return [opener, app_name] + args
                        return [opener, app_name] + args

                # Fall back to executing the app name directly (may raise FileNotFoundError)
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
