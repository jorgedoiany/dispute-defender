"""Local approval page (T-006, ADR-004, ADR-010)."""
from .app import create_app
from .csrf import CsrfTokens
from .settings import load_send_mode

__all__ = ["CsrfTokens", "create_app", "load_send_mode"]
