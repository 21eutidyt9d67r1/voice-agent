"""Render the Portal's Markdown guides as standalone HTML pages.

Only the Markdown the guides use is supported: headings, paragraphs, bullet and numbered
lists, pipe tables, fenced code blocks, inline code, bold text, and links. All text is
HTML-escaped first, so the output never contains markup from the source.
"""

from __future__ import annotations

import html
import re

# Repository-relative guide links that the Portal serves itself.
GUIDE_ROUTES = {
    "./03_run_samples.md": "/guide/run-samples",
    "03_run_samples.md": "/guide/run-samples",
    "./05_connect_real_tools.md": "/guide/real-tools",
    "05_connect_real_tools.md": "/guide/real-tools",
    "./06_logic_apps_mcp_servers.md": "/guide/logic-apps-mcp",
    "06_logic_apps_mcp_servers.md": "/guide/logic-apps-mcp",
}
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+\.\s+(.*)$")
_TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ margin: 0; background: #f6f8f7; color: #1f2d28;
  font: 15px/1.6 "Segoe UI", system-ui, -apple-system, sans-serif; }}
main {{ max-width: 920px; margin: 0 auto; padding: 32px 28px 64px; background: #fff;
  min-height: 100vh; box-shadow: 0 0 0 1px #e3ebe7; }}
h1 {{ font-size: 28px; margin: 0 0 18px; color: #134e3a; }}
h2 {{ font-size: 21px; margin: 34px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e3ebe7; color: #134e3a; }}
h3 {{ font-size: 17px; margin: 24px 0 8px; }}
h4 {{ font-size: 15px; margin: 18px 0 6px; }}
p, li {{ margin: 6px 0; }}
ul, ol {{ padding-left: 24px; }}
a {{ color: #075e7a; font-weight: 600; }}
code {{ font: 13px/1.5 Consolas, "Cascadia Code", monospace; background: #eef4f1; padding: 1px 4px;
  border-radius: 4px; overflow-wrap: anywhere; }}
pre {{ background: #10231c; color: #e7f3ee; padding: 14px 16px; border-radius: 8px; overflow-x: auto; }}
pre code {{ background: none; color: inherit; padding: 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; display: block; overflow-x: auto; }}
th, td {{ border: 1px solid #dbe5e0; padding: 7px 9px; text-align: left; vertical-align: top; }}
th {{ background: #eef4f1; }}
.back {{ display: inline-block; margin-bottom: 18px; font-size: 13px; }}
</style>
</head>
<body>
<main>
<a class="back" href="/editor">&larr; Back to the Editor</a>
{body}
</main>
</body>
</html>
"""


def _href(target: str) -> str | None:
    """A safe link target, or None to render the text without a link."""
    if target in GUIDE_ROUTES:
        return GUIDE_ROUTES[target]
    if target.startswith("https://") or target.startswith("#"):
        return target
    return None


def inline(text: str) -> str:
    """Escape text and render inline code, bold, and links."""
    pieces: list[str] = []
    position = 0
    for match in _CODE.finditer(text):
        pieces.append(_inline_text(text[position : match.start()]))
        pieces.append(f"<code>{html.escape(match.group(1))}</code>")
        position = match.end()
    pieces.append(_inline_text(text[position:]))
    return "".join(pieces)


def _inline_text(text: str) -> str:
    output: list[str] = []
    position = 0
    for match in _LINK.finditer(text):
        output.append(_bold(html.escape(text[position : match.start()])))
        label = _bold(html.escape(match.group(1)))
        target = _href(match.group(2))
        output.append(
            f'<a href="{html.escape(target)}" target="_blank" rel="noreferrer">{label}</a>' if target else label
        )
        position = match.end()
    output.append(_bold(html.escape(text[position:])))
    return "".join(output)


def _bold(escaped: str) -> str:
    return _BOLD.sub(r"<strong>\1</strong>", escaped)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown(text: str) -> tuple[str, str]:
    """Render Markdown to an HTML fragment; return (title, body)."""
    lines = text.splitlines()
    title = "Guide"
    out: list[str] = []
    paragraph: list[str] = []
    list_tag = ""
    item: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_item() -> None:
        if item:
            out.append(f"<li>{inline(' '.join(item))}</li>")
            item.clear()

    def close_list() -> None:
        nonlocal list_tag
        flush_item()
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(_dedent(block)))}</code></pre>")
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and _TABLE_RULE.match(lines[index + 1].strip()):
            flush_paragraph()
            close_list()
            header = "".join(f"<th>{inline(cell)}</th>" for cell in _cells(stripped))
            rows: list[str] = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in _cells(lines[index])) + "</tr>")
                index += 1
            out.append(f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>")
            continue
        heading = _HEADING.match(stripped)
        bullet = _BULLET.match(line)
        numbered = _NUMBERED.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            if level == 1:
                title = heading.group(2)
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            flush_item()
            item.append((bullet or numbered).group(2))
        elif not stripped:
            flush_paragraph()
            if list_tag and index + 1 < len(lines) and lines[index + 1].startswith((" ", "\t")):
                index += 1
                continue
            close_list()
        elif list_tag and line.startswith((" ", "\t")):
            item.append(stripped)
        else:
            close_list()
            paragraph.append(stripped)
        index += 1
    flush_paragraph()
    close_list()
    return title, "\n".join(out)


def _dedent(block: list[str]) -> list[str]:
    indents = [len(line) - len(line.lstrip()) for line in block if line.strip()]
    margin = min(indents) if indents else 0
    return [line[margin:] for line in block]


def render_page(text: str) -> str:
    """Render a Markdown guide as a complete HTML page."""
    title, body = render_markdown(text)
    return PAGE.format(title=html.escape(title), body=body)
