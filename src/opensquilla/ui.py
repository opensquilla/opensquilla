"""Shared terminal presentation helpers."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)

ACCENT = "#F56600"
ACCENT_SOFT = "#FF8A4C"
ACCENT_DEEP = "#B0440A"
ACCENT_DIM = "#7A2C00"
ACCENT_INK = "#1a0e02"


def error_panel(message: str, *, title: str = "Error") -> Panel:
    """Return a compact operator-facing error panel."""
    return Panel(f"[red]{markup_escape(message)}[/red]", title=title, border_style="red")


def warning_panel(message: str, *, title: str = "Warning") -> Panel:
    """Return a brand-tinted warning panel for recoverable setup gaps."""
    body = f"[bold {ACCENT}]▌ {markup_escape(title)}[/bold {ACCENT}]"
    body += f"\n[dim]{markup_escape(message)}[/dim]"
    return Panel(body, border_style=ACCENT_SOFT, padding=(0, 2))


def markup_escape(value: object) -> str:
    """Escape dynamic text before interpolating it into Rich markup."""
    return escape(str(value))


def banner_panel(title: str, subtitle: str = "") -> Panel:
    """Brand-tinted header panel used by onboarding / setup surfaces."""
    body = f"[bold {ACCENT}]▌ {markup_escape(title)}[/bold {ACCENT}]"
    if subtitle:
        body += f"\n[dim]{markup_escape(subtitle)}[/dim]"
    return Panel(
        body,
        border_style=ACCENT,
        padding=(0, 2),
    )


def section_rule(label: str) -> str:
    """A compact rule string with the brand accent for inline section markers."""
    return (
        f"[bold {ACCENT}]┄┄┄ {markup_escape(label)} "
        f"[/bold {ACCENT}][{ACCENT_DIM}]"
        + "─" * 6
        + "[/]"
    )


def questionary_style():
    """Build a questionary Style aligned with the WebUI brand orange.

    Returns ``None`` if questionary is unavailable or stubbed in tests.
    """
    try:
        from questionary import Style
    except (ImportError, AttributeError):
        return None

    return Style(
        [
            ("qmark", f"fg:{ACCENT} bold"),
            ("question", "bold"),
            ("answer", f"fg:{ACCENT_SOFT} bold"),
            ("pointer", f"fg:{ACCENT} bold"),
            ("highlighted", f"fg:{ACCENT} bold"),
            ("selected", f"fg:{ACCENT_SOFT}"),
            ("separator", f"fg:{ACCENT_DIM}"),
            ("instruction", "fg:#7a7a7a"),
            ("text", ""),
            ("disabled", "fg:#666666 italic"),
        ]
    )
