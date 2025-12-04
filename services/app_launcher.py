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
                # Use start command on Windows to launch in new process
                subprocess.Popen(
                    command,
                    shell=True,
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
        
        if self.os_type == "Windows":
            # Windows application launching
            if os.path.exists(app_name):
                # Full path provided
                return ["start", "", app_name] + args
            else:
                # Try common locations and app names
                common_apps = self._get_windows_app_path(app_name)
                if common_apps:
                    return ["start", "", common_apps] + args
                else:
                    # Try as command
                    return ["start", "", app_name] + args
        
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
        app_name_lower = app_name.lower()
        
        # Common application mappings
        app_mappings = {
            'notepad': 'notepad.exe',
            'calculator': 'calc.exe',
            'calc': 'calc.exe',
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
        }
        
        # Check if app name is in mappings
        if app_name_lower in app_mappings:
            app_path = app_mappings[app_name_lower]
            if os.path.exists(app_path):
                return app_path
        
        # Try program files directories
        program_files = [
            os.environ.get('ProgramFiles', r'C:\Program Files'),
            os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        ]
        
        for pf_dir in program_files:
            possible_path = os.path.join(pf_dir, app_name, f"{app_name}.exe")
            if os.path.exists(possible_path):
                return possible_path
        
        return None
