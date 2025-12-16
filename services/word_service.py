"""
Microsoft Word Service
Handles Word document operations including creation, editing, formatting, and manipulation
"""

import os
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
import platform

logger = logging.getLogger(__name__)

# Try to import python-docx, but handle gracefully if not installed
try:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    logger.warning("python-docx not installed. Word features will be limited. Install with: pip install python-docx")


class WordService:
    """Service for Microsoft Word document operations"""
    
    def __init__(self):
        self.os_type = platform.system()
        self.default_documents_dir = self._get_default_documents_dir()
        logger.info(f"Word Service initialized for {self.os_type}")
        
        if not HAS_DOCX:
            logger.warning("python-docx library not available. Some Word features may not work.")
    
    def _get_default_documents_dir(self) -> str:
        """Get the default documents directory for the OS"""
        if self.os_type == "Windows":
            return os.path.join(os.path.expanduser("~"), "Documents")
        elif self.os_type == "Darwin":
            return os.path.join(os.path.expanduser("~"), "Documents")
        else:
            return os.path.join(os.path.expanduser("~"), "Documents")
    
    async def initialize(self):
        """Initialize the Word service"""
        try:
            # Ensure documents directory exists
            os.makedirs(self.default_documents_dir, exist_ok=True)
            logger.info(f"Word service initialized. Documents directory: {self.default_documents_dir}")
        except Exception as e:
            logger.error(f"Error initializing Word service: {e}")
    
    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Word service cleanup completed")
    
    async def create_document(
        self,
        file_path: str,
        content: Optional[str] = None,
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new Word document
        
        Args:
            file_path: Path where the document should be saved
            content: Optional initial content for the document
            title: Optional document title
        
        Returns:
            Dictionary with success status and file path
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed. Install with: pip install python-docx"
            }
        
        try:
            # Normalize the file path
            file_path = os.path.normpath(file_path)
            
            # Ensure directory exists
            file_dir = os.path.dirname(file_path) or self.default_documents_dir
            if file_dir:
                os.makedirs(file_dir, exist_ok=True)
            
            # Create new document
            doc = Document()
            
            # Add title if provided
            if title:
                title_para = doc.add_heading(title, level=1)
                title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Add content if provided
            if content:
                doc.add_paragraph(content)
            
            # Save document
            doc.save(file_path)
            
            logger.info(f"Created Word document: {file_path}")
            return {
                "success": True,
                "file_path": file_path,
                "message": f"Document created successfully at {file_path}"
            }
        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def open_document(self, file_path: str) -> Dict[str, Any]:
        """
        Open an existing Word document
        
        Args:
            file_path: Path to the document
        
        Returns:
            Dictionary with document information
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            
            # Extract document information
            paragraphs = [para.text for para in doc.paragraphs]
            
            return {
                "success": True,
                "file_path": file_path,
                "paragraph_count": len(paragraphs),
                "content": "\n".join(paragraphs),
                "message": f"Document opened successfully"
            }
        except Exception as e:
            logger.error(f"Error opening document: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def add_text(
        self,
        file_path: str,
        text: str,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        font_name: Optional[str] = None,
        font_size: Optional[int] = None,
        color: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add text to a Word document
        
        Args:
            file_path: Path to the document
            text: Text to add
            bold: Make text bold
            italic: Make text italic
            underline: Underline text
            font_name: Font name (e.g., "Arial", "Times New Roman")
            font_size: Font size in points
            color: Text color (hex format, e.g., "#FF0000" for red)
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            para = doc.add_paragraph()
            run = para.add_run(text)
            
            # Apply formatting
            run.bold = bold
            run.italic = italic
            run.underline = underline
            
            if font_name:
                run.font.name = font_name
                run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
            
            if font_size:
                run.font.size = Pt(font_size)
            
            if color:
                # Convert hex color to RGB
                color = color.lstrip('#')
                rgb = RGBColor(int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
                run.font.color.rgb = rgb
            
            doc.save(file_path)
            
            logger.info(f"Added text to document: {file_path}")
            return {
                "success": True,
                "message": "Text added successfully"
            }
        except Exception as e:
            logger.error(f"Error adding text: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def format_paragraph(
        self,
        file_path: str,
        paragraph_index: int,
        alignment: Optional[str] = None,
        line_spacing: Optional[float] = None,
        space_before: Optional[float] = None,
        space_after: Optional[float] = None,
        left_indent: Optional[float] = None,
        right_indent: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Format a paragraph in a Word document
        
        Args:
            file_path: Path to the document
            paragraph_index: Index of the paragraph to format (0-based)
            alignment: Paragraph alignment ("left", "center", "right", "justify")
            line_spacing: Line spacing (e.g., 1.5, 2.0)
            space_before: Space before paragraph in points
            space_after: Space after paragraph in points
            left_indent: Left indent in inches
            right_indent: Right indent in inches
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            
            if paragraph_index >= len(doc.paragraphs):
                return {
                    "success": False,
                    "error": f"Paragraph index {paragraph_index} out of range"
                }
            
            para = doc.paragraphs[paragraph_index]
            
            # Set alignment
            if alignment:
                align_map = {
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
                }
                if alignment.lower() in align_map:
                    para.alignment = align_map[alignment.lower()]
            
            # Set line spacing
            if line_spacing is not None:
                para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
                para.paragraph_format.line_spacing = line_spacing
            
            # Set spacing
            if space_before is not None:
                para.paragraph_format.space_before = Pt(space_before)
            if space_after is not None:
                para.paragraph_format.space_after = Pt(space_after)
            
            # Set indentation
            if left_indent is not None:
                para.paragraph_format.left_indent = Inches(left_indent)
            if right_indent is not None:
                para.paragraph_format.right_indent = Inches(right_indent)
            
            doc.save(file_path)
            
            logger.info(f"Formatted paragraph {paragraph_index} in document: {file_path}")
            return {
                "success": True,
                "message": "Paragraph formatted successfully"
            }
        except Exception as e:
            logger.error(f"Error formatting paragraph: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def add_heading(
        self,
        file_path: str,
        text: str,
        level: int = 1
    ) -> Dict[str, Any]:
        """
        Add a heading to a Word document
        
        Args:
            file_path: Path to the document
            text: Heading text
            level: Heading level (1-9)
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            doc.add_heading(text, level=min(level, 9))
            doc.save(file_path)
            
            logger.info(f"Added heading to document: {file_path}")
            return {
                "success": True,
                "message": "Heading added successfully"
            }
        except Exception as e:
            logger.error(f"Error adding heading: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def add_list(
        self,
        file_path: str,
        items: List[str],
        numbered: bool = False
    ) -> Dict[str, Any]:
        """
        Add a list (bulleted or numbered) to a Word document
        
        Args:
            file_path: Path to the document
            items: List of items to add
            numbered: True for numbered list, False for bulleted list
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            
            for item in items:
                para = doc.add_paragraph(item, style='List Number' if numbered else 'List Bullet')
            
            doc.save(file_path)
            
            logger.info(f"Added list to document: {file_path}")
            return {
                "success": True,
                "message": f"List with {len(items)} items added successfully"
            }
        except Exception as e:
            logger.error(f"Error adding list: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def add_table(
        self,
        file_path: str,
        rows: int,
        cols: int,
        data: Optional[List[List[str]]] = None,
        header_row: bool = False
    ) -> Dict[str, Any]:
        """
        Add a table to a Word document
        
        Args:
            file_path: Path to the document
            rows: Number of rows
            cols: Number of columns
            data: Optional 2D list of data to populate the table
            header_row: Whether the first row should be formatted as a header
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            table = doc.add_table(rows=rows, cols=cols)
            
            # Populate table with data if provided
            if data:
                for i, row_data in enumerate(data[:rows]):
                    for j, cell_data in enumerate(row_data[:cols]):
                        table.rows[i].cells[j].text = str(cell_data)
            
            # Format header row if requested
            if header_row and rows > 0:
                header_cells = table.rows[0].cells
                for cell in header_cells:
                    cell.paragraphs[0].runs[0].bold = True
            
            doc.save(file_path)
            
            logger.info(f"Added table to document: {file_path}")
            return {
                "success": True,
                "message": f"Table with {rows}x{cols} dimensions added successfully"
            }
        except Exception as e:
            logger.error(f"Error adding table: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def find_replace(
        self,
        file_path: str,
        find_text: str,
        replace_text: str,
        replace_all: bool = True
    ) -> Dict[str, Any]:
        """
        Find and replace text in a Word document
        
        Args:
            file_path: Path to the document
            find_text: Text to find
            replace_text: Text to replace with
            replace_all: Whether to replace all occurrences
        
        Returns:
            Dictionary with success status and replacement count
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            replacement_count = 0
            
            for para in doc.paragraphs:
                if find_text in para.text:
                    para.text = para.text.replace(find_text, replace_text)
                    replacement_count += para.text.count(replace_text) if replace_all else 1
                    if not replace_all:
                        break
            
            # Also search in tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if find_text in cell.text:
                            cell.text = cell.text.replace(find_text, replace_text)
                            replacement_count += cell.text.count(replace_text) if replace_all else 1
                            if not replace_all:
                                break
            
            doc.save(file_path)
            
            logger.info(f"Find and replace completed in document: {file_path}")
            return {
                "success": True,
                "message": f"Replaced {replacement_count} occurrence(s)",
                "replacement_count": replacement_count
            }
        except Exception as e:
            logger.error(f"Error in find and replace: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def set_page_setup(
        self,
        file_path: str,
        margins: Optional[Dict[str, float]] = None,
        orientation: Optional[str] = None,
        page_size: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Set page setup options for a Word document
        
        Args:
            file_path: Path to the document
            margins: Dictionary with margin values in inches (top, bottom, left, right)
            orientation: Page orientation ("portrait" or "landscape")
            page_size: Page size (e.g., "Letter", "A4", "Legal")
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            from docx.enum.section import WD_ORIENT, WD_SECTION
            from docx.shared import Mm
            
            doc = Document(file_path)
            section = doc.sections[0]
            
            # Set margins
            if margins:
                if 'top' in margins:
                    section.top_margin = Inches(margins['top'])
                if 'bottom' in margins:
                    section.bottom_margin = Inches(margins['bottom'])
                if 'left' in margins:
                    section.left_margin = Inches(margins['left'])
                if 'right' in margins:
                    section.right_margin = Inches(margins['right'])
            
            # Set orientation
            if orientation:
                if orientation.lower() == "landscape":
                    section.orientation = WD_ORIENT.LANDSCAPE
                elif orientation.lower() == "portrait":
                    section.orientation = WD_ORIENT.PORTRAIT
            
            # Set page size
            if page_size:
                page_sizes = {
                    "Letter": (Inches(8.5), Inches(11)),
                    "A4": (Mm(210), Mm(297)),
                    "Legal": (Inches(8.5), Inches(14)),
                    "A3": (Mm(297), Mm(420)),
                    "A5": (Mm(148), Mm(210))
                }
                if page_size in page_sizes:
                    section.page_width, section.page_height = page_sizes[page_size]
            
            doc.save(file_path)
            
            logger.info(f"Page setup updated for document: {file_path}")
            return {
                "success": True,
                "message": "Page setup updated successfully"
            }
        except Exception as e:
            logger.error(f"Error setting page setup: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def save_document(self, file_path: str, new_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Save a Word document (or save as a new file)
        
        Args:
            file_path: Current path to the document
            new_path: Optional new path to save as
        
        Returns:
            Dictionary with success status
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            save_path = new_path or file_path
            
            # Ensure directory exists
            save_dir = os.path.dirname(save_path)
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
            
            doc.save(save_path)
            
            logger.info(f"Document saved: {save_path}")
            return {
                "success": True,
                "file_path": save_path,
                "message": f"Document saved successfully to {save_path}"
            }
        except Exception as e:
            logger.error(f"Error saving document: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_document_info(self, file_path: str) -> Dict[str, Any]:
        """
        Get information about a Word document
        
        Args:
            file_path: Path to the document
        
        Returns:
            Dictionary with document information
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed"
            }
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"Document not found: {file_path}"
                }
            
            doc = Document(file_path)
            
            # Get file stats
            file_stats = os.stat(file_path)
            
            info = {
                "success": True,
                "file_path": file_path,
                "file_size": file_stats.st_size,
                "paragraph_count": len(doc.paragraphs),
                "table_count": len(doc.tables),
                "section_count": len(doc.sections),
                "created": file_stats.st_ctime,
                "modified": file_stats.st_mtime
            }
            
            # Get first few paragraphs as preview
            preview_paragraphs = [para.text for para in doc.paragraphs[:5]]
            info["preview"] = "\n".join(preview_paragraphs)
            
            return info
        except Exception as e:
            logger.error(f"Error getting document info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def save_html_content(
        self,
        file_path: str,
        html_content: str
    ) -> Dict[str, Any]:
        """
        Save HTML content to a Word document, preserving formatting
        
        Args:
            file_path: Path where the document should be saved
            html_content: HTML content from contenteditable div
        
        Returns:
            Dictionary with success status and file path
        """
        if not HAS_DOCX:
            return {
                "success": False,
                "error": "python-docx library not installed. Install with: pip install python-docx"
            }
        
        try:
            from html.parser import HTMLParser
            import re
            
            # Log the HTML content for debugging (first 500 chars)
            logger.info(f"Saving HTML content to {file_path}, HTML length: {len(html_content)}, preview: {html_content[:500]}")
            
            # Normalize the file path
            original_path = file_path
            file_path = os.path.normpath(file_path)
            logger.info(f"Normalized path: {file_path} (original: {original_path})")
            
            # Ensure directory exists
            file_dir = os.path.dirname(file_path)
            if not file_dir:
                # If no directory specified, use default
                file_dir = self.default_documents_dir
                file_path = os.path.join(file_dir, os.path.basename(file_path))
                logger.warning(f"No directory in path, using default: {file_path}")
            
            logger.info(f"Creating directory if needed: {file_dir}")
            try:
                os.makedirs(file_dir, exist_ok=True)
                logger.info(f"Directory ready: {file_dir}")
            except Exception as dir_error:
                logger.error(f"Error creating directory {file_dir}: {dir_error}")
                return {
                    "success": False,
                    "error": f"Cannot create directory '{file_dir}': {str(dir_error)}"
                }
            
            logger.info(f"Final file path: {file_path}")
            
            # Create new document
            doc = Document()
            
            # Parse HTML and convert to Word document
            class HTMLToWordParser(HTMLParser):
                def __init__(self, doc):
                    super().__init__()
                    self.doc = doc
                    self.current_para = None
                    self.current_run = None
                    
                def handle_starttag(self, tag, attrs):
                    attrs_dict = dict(attrs)
                    
                    if tag in ['p', 'div', 'br']:
                        # Start new paragraph
                        if tag == 'br' and self.current_para:
                            # Just add line break
                            if self.current_run:
                                self.current_run.add_break()
                            else:
                                self.current_para.add_run().add_break()
                        else:
                            self.current_para = self.doc.add_paragraph()
                            self.current_run = None
                    
                    elif tag == 'strong' or tag == 'b':
                        # Bold
                        if self.current_para is None:
                            self.current_para = self.doc.add_paragraph()
                        if self.current_run is None:
                            self.current_run = self.current_para.add_run()
                        self.current_run.bold = True
                    
                    elif tag == 'em' or tag == 'i':
                        # Italic
                        if self.current_para is None:
                            self.current_para = self.doc.add_paragraph()
                        if self.current_run is None:
                            self.current_run = self.current_para.add_run()
                        self.current_run.italic = True
                    
                    elif tag == 'u':
                        # Underline
                        if self.current_para is None:
                            self.current_para = self.doc.add_paragraph()
                        if self.current_run is None:
                            self.current_run = self.current_para.add_run()
                        self.current_run.underline = True
                    
                    elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        # Heading
                        level = int(tag[1])
                        self.current_para = self.doc.add_heading(level=level)
                        self.current_run = None
                    
                    elif tag == 'span' or tag == 'font':
                        # Handle inline styles
                        if self.current_para is None:
                            self.current_para = self.doc.add_paragraph()
                        if self.current_run is None:
                            self.current_run = self.current_para.add_run()
                        
                        # Parse style attribute
                        style = attrs_dict.get('style', '')
                        if style:
                            # Parse font-size
                            font_size_match = re.search(r'font-size:\s*(\d+)pt', style)
                            if font_size_match:
                                self.current_run.font.size = Pt(int(font_size_match.group(1)))
                            
                            # Parse font-family
                            font_family_match = re.search(r'font-family:\s*([^;]+)', style)
                            if font_family_match:
                                font_name = font_family_match.group(1).strip().strip('"').strip("'").split(',')[0].strip()
                                self.current_run.font.name = font_name
                                self.current_run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
                            
                            # Parse color
                            color_match = re.search(r'color:\s*(#[0-9a-fA-F]{6}|rgb\([^)]+\))', style)
                            if color_match:
                                color_str = color_match.group(1)
                                if color_str.startswith('#'):
                                    # Hex color
                                    color = color_str.lstrip('#')
                                    rgb = RGBColor(int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
                                    self.current_run.font.color.rgb = rgb
                                elif color_str.startswith('rgb'):
                                    # RGB color
                                    rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color_str)
                                    if rgb_match:
                                        rgb = RGBColor(int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3)))
                                        self.current_run.font.color.rgb = rgb
                            
                            # Parse text-align
                            align_match = re.search(r'text-align:\s*(\w+)', style)
                            if align_match and self.current_para:
                                align = align_match.group(1).lower()
                                align_map = {
                                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                                    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
                                }
                                if align in align_map:
                                    self.current_para.alignment = align_map[align]
                    
                    # Handle font tag attributes
                    if tag == 'font':
                        if 'size' in attrs_dict:
                            try:
                                size = int(attrs_dict['size'])
                                if self.current_para is None:
                                    self.current_para = self.doc.add_paragraph()
                                if self.current_run is None:
                                    self.current_run = self.current_para.add_run()
                                # Font size in points (approximate conversion)
                                self.current_run.font.size = Pt(size * 2 + 8)
                            except:
                                pass
                        if 'face' in attrs_dict:
                            if self.current_para is None:
                                self.current_para = self.doc.add_paragraph()
                            if self.current_run is None:
                                self.current_run = self.current_para.add_run()
                            self.current_run.font.name = attrs_dict['face']
                            self.current_run._element.rPr.rFonts.set(qn('w:eastAsia'), attrs_dict['face'])
                        if 'color' in attrs_dict:
                            if self.current_para is None:
                                self.current_para = self.doc.add_paragraph()
                            if self.current_run is None:
                                self.current_run = self.current_para.add_run()
                            color = attrs_dict['color'].lstrip('#')
                            if len(color) == 6:
                                rgb = RGBColor(int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
                                self.current_run.font.color.rgb = rgb
                
                def handle_endtag(self, tag):
                    if tag in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        # End paragraph
                        self.current_para = None
                        self.current_run = None
                    elif tag in ['strong', 'b', 'em', 'i', 'u', 'span', 'font']:
                        # End run - create new run for next text
                        self.current_run = None
                
                def handle_data(self, data):
                    # Add text to current run
                    try:
                        # Decode HTML entities
                        import html
                        data = html.unescape(data)
                        
                        if data.strip() or (self.current_run and len(self.current_run.text) == 0):
                            if self.current_para is None:
                                self.current_para = self.doc.add_paragraph()
                            if self.current_run is None:
                                self.current_run = self.current_para.add_run()
                            self.current_run.add_text(data)
                    except Exception as e:
                        logger.warning(f"Error handling data in HTML parser: {e}")
                        # Try to add text anyway
                        if self.current_para is None:
                            self.current_para = self.doc.add_paragraph()
                        if self.current_run is None:
                            self.current_run = self.current_para.add_run()
                        try:
                            self.current_run.add_text(str(data))
                        except:
                            pass
            
            # Handle empty or minimal content
            if not html_content or not html_content.strip():
                # If content is empty, add at least one paragraph
                doc.add_paragraph()
            else:
                # Parse HTML content
                parser = HTMLToWordParser(doc)
                try:
                    # Clean up HTML content - remove script and style tags
                    import re
                    cleaned_html = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                    cleaned_html = re.sub(r'<style[^>]*>.*?</style>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)
                    
                    parser.feed(cleaned_html)
                    parser.close()  # Ensure parser is closed
                except Exception as parse_error:
                    logger.warning(f"HTML parsing error (trying fallback): {parse_error}")
                    import traceback
                    logger.warning(traceback.format_exc())
                    # Fallback: try to extract plain text and save
                    import html
                    plain_text = html.unescape(html_content)
                    # Remove HTML tags
                    plain_text = re.sub(r'<[^>]+>', '', plain_text)
                    if plain_text.strip():
                        doc.add_paragraph(plain_text.strip())
                    else:
                        doc.add_paragraph()
            
            # Ensure at least one paragraph exists
            if len(doc.paragraphs) == 0:
                doc.add_paragraph()
            
            # Save document
            doc.save(file_path)
            
            logger.info(f"Saved HTML content to Word document: {file_path}")
            return {
                "success": True,
                "file_path": file_path,
                "message": f"Document saved successfully at {file_path}"
            }
        except Exception as e:
            logger.error(f"Error saving HTML content: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e)
            }

