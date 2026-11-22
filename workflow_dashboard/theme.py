"""Read the shared values needed by renderers that cannot consume CSS directly."""

import re
from pathlib import Path


STYLESHEET = Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
_css = re.sub(r"/\*.*?\*/", "", STYLESHEET, flags=re.DOTALL)
_root = re.search(r":root\s*\{([^}]+)\}", _css).group(1)
_TOKENS = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", _root))


def value(name: str, _seen: tuple[str, ...] = ()) -> str:
    """Resolve literal values and var(--token) aliases from the first :root block."""
    if name in _seen:
        raise ValueError(f"Circular theme reference: {' -> '.join((*_seen, name))}")
    if name not in _TOKENS:
        raise ValueError(f"Missing theme token: --{name}")
    return re.sub(
        r"var\(--([\w-]+)\)",
        lambda match: value(match[1], (*_seen, name)),
        _TOKENS[name],
    ).strip()


def number(name: str) -> float:
    """Plotly and native widgets need unitless numbers rather than CSS lengths."""
    return float(value(name))


def integers(name: str) -> tuple[int, ...]:
    """Read native padding pairs and workbook column widths."""
    return tuple(map(int, value(name).split()))


def margin(name: str) -> dict[str, int]:
    """Translate CSS margin order to Plotly's named sides."""
    return dict(zip(("t", "r", "b", "l"), integers(name), strict=True))


def excel_color(name: str) -> str:
    """Excel accepts RGB hex values without CSS's leading #."""
    color = value(name)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError(f"Workbook theme token --{name} must be a six-digit hex color")
    return color[1:].upper()
