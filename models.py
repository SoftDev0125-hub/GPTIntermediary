"""
Database models for GPTIntermediary application
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    """User accounts and authentication"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=True)  # For future authentication
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    telegram_sessions = relationship("TelegramSession", back_populates="user", cascade="all, delete-orphan")
    excel_files = relationship("ExcelFile", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"


class Conversation(Base):
    """Chat conversations/threads"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=True)
    model = Column(String(100), default="gpt-4")  # GPT model used
    system_prompt = Column(Text, nullable=True)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Metadata for conversation
    metadata = Column(JSON, nullable=True)  # Store additional info as JSON

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")

    def __repr__(self):
        return f"<Conversation(id={self.id}, title='{self.title}')>"


class Message(Base):
    """Individual messages in conversations"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=True)  # Token count for the message
    cost = Column(Float, nullable=True)  # Cost for this message
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Additional metadata
    metadata = Column(JSON, nullable=True)  # Function calls, attachments, etc.

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return f"<Message(id={self.id}, role='{self.role}')>"


class UserPreference(Base):
    """User preferences and settings"""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Chat preferences
    default_model = Column(String(100), default="gpt-4")
    default_temperature = Column(Float, default=0.7)
    default_system_prompt = Column(Text, nullable=True)
    
    # UI preferences
    theme = Column(String(20), default="light")  # 'light', 'dark'
    language = Column(String(10), default="en")
    
    # Notification preferences
    enable_notifications = Column(Boolean, default=True)
    
    # Other settings as JSON
    settings = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="preferences")

    def __repr__(self):
        return f"<UserPreference(user_id={self.user_id})>"


class TelegramSession(Base):
    """Telegram session data and authentication"""
    __tablename__ = "telegram_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Telegram account info
    phone_number = Column(String(20), unique=True, nullable=False)
    telegram_user_id = Column(String(50), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    
    # Session data (encrypted in production!)
    session_string = Column(Text, nullable=True)  # Encrypted Telegram session
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    authenticated_at = Column(DateTime(timezone=True), nullable=True)
    last_used = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="telegram_sessions")

    def __repr__(self):
        return f"<TelegramSession(id={self.id}, phone='{self.phone_number}')>"


class ExcelFile(Base):
    """Excel file metadata and history"""
    __tablename__ = "excel_files"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # File information
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)  # Size in bytes
    
    # Excel metadata
    sheet_names = Column(JSON, nullable=True)  # List of sheet names
    total_rows = Column(Integer, nullable=True)
    total_columns = Column(Integer, nullable=True)
    
    # Timestamps
    last_opened = Column(DateTime(timezone=True), nullable=True)
    last_modified = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Additional metadata
    metadata = Column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="excel_files")

    def __repr__(self):
        return f"<ExcelFile(id={self.id}, name='{self.file_name}')>"


class APIKey(Base):
    """Store API keys for various services (encrypted in production!)"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    
    # API key information
    service_name = Column(String(100), nullable=False)  # 'openai', 'google', 'slack', etc.
    api_key = Column(Text, nullable=False)  # Should be encrypted in production
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<APIKey(id={self.id}, service='{self.service_name}')>"


class SystemLog(Base):
    """System logs and audit trail"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Log information
    level = Column(String(20), nullable=False)  # 'INFO', 'WARNING', 'ERROR', 'DEBUG'
    action = Column(String(100), nullable=False)  # 'user_login', 'file_opened', etc.
    message = Column(Text, nullable=True)
    
    # Additional context
    metadata = Column(JSON, nullable=True)  # IP address, user agent, etc.
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<SystemLog(id={self.id}, action='{self.action}')>"

