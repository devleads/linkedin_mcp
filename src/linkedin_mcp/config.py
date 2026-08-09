"""Configuration management for LinkedIn MCP Server."""

import logging
import sys
from typing import Optional, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = Field(
        default="postgresql://linkedin:linkedin@localhost:5432/linkedin",
        description="PostgreSQL connection URL"
    )
    linkedin_credential_encryption_key: str = Field(
        default="",
        description="Fernet key for encrypting/decrypting LinkedIn profile credentials",
    )
    
    # Proxy provider selection — choose one of: oxylabs, ipfoxy, apify
    proxy_provider: Literal["oxylabs", "ipfoxy", "apify"] = Field(
        default="oxylabs",
        description="Proxy provider backend (oxylabs, ipfoxy, or apify)",
    )

    # Oxylabs credentials (required when PROXY_PROVIDER=oxylabs)
    oxylabs_username: str = Field(default="", description="Oxylabs username (without customer- prefix)")
    oxylabs_password: str = Field(default="", description="Oxylabs password")
    oxylabs_proxy_type: Literal["mobile", "residentials"] = Field(
        default="mobile",
        description="Oxylabs product type: mobile or residentials",
    )
    oxylabs_residential_host: str = Field(
        default="pr.oxylabs.io",
        description="Default Oxylabs Residential entry host",
    )

    # Apify residential proxy (required when PROXY_PROVIDER=apify)
    # Get password from https://console.apify.com/settings/proxy
    apify_proxy_password: str = Field(
        default="",
        description="Apify proxy password for residential proxy authentication",
    )
    apify_proxy_groups: str = Field(
        default="RESIDENTIAL",
        description="Apify proxy group (RESIDENTIAL, DATACENTER, etc.)",
    )
    
    # Proxy requirement - must be True
    proxy_required: bool = Field(default=True, description="Require proxy for all connections")
    
    # Browser settings
    headless: bool = Field(default=False, description="Run browser in headless mode (NOT recommended)")
    
    # MCP Server
    mcp_host: str = Field(default="0.0.0.0", description="MCP server host")
    mcp_port: int = Field(default=8765, description="MCP server port")
    
    # Browser debug delay (seconds to keep browser open after request, 0 for production)
    browser_debug_delay: int = Field(default=0, description="Seconds to keep browser open after request (0 for production)")
    
    # Browser isolation - if True, each request gets its own browser window (no session reuse)
    browser_isolate_sessions: bool = Field(default=False, description="Each request opens its own browser window")

    # Challenge lock cooldown
    challenge_cooldown_minutes: int = Field(
        default=15,
        description="Minutes to block tool calls for a profile after challenge/auth-wall detection",
    )
    
    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    log_format: Literal["json", "text"] = Field(
        default="text", description="Log format (json for production, text for development)"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings: Optional[Settings] = None
_logging_configured: bool = False


def get_settings() -> Settings:
    """Get application settings (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def setup_logging() -> None:
    """Configure logging based on settings. Call once at application startup."""
    global _logging_configured
    if _logging_configured:
        return
    
    settings = get_settings()
    level = getattr(logging, settings.log_level)
    
    # Clear existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    # Set format based on config
    if settings.log_format == "json":
        # JSON format for production (easy to parse by log aggregators)
        formatter = JsonFormatter()
    else:
        # Human-readable format for development
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    
    # Reduce noise from third-party libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    _logging_configured = True
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured: level={settings.log_level}, format={settings.log_format}")


class JsonFormatter(logging.Formatter):
    """JSON log formatter for production environments."""
    
    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone
        
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra
        
        return json.dumps(log_data)
