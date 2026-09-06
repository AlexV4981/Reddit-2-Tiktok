from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser

from markdown_it import MarkdownIt


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def terminal_text(text: str) -> str:
    """Never allow a Reddit title to inject terminal control sequences."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return " ".join(
        "".join(" " if unicodedata.category(c).startswith("C") else c for c in text).split()
    )


def plain_text(markdown: str) -> str:
    parser = _HTMLText()
    parser.feed(html.unescape(markdown))
    clean = "".join(parser.parts)
    parts = []
    for token in MarkdownIt().parse(clean):
        if token.type == "inline":
            for child in token.children or []:
                if child.type in {"text", "code_inline"}:
                    parts.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    parts.append(" ")
            parts.append(" ")
        elif token.type in {"fence", "code_block"}:
            parts.append(token.content + " ")
    text = re.sub(r"https?://\S+|www\.\S+", "", "".join(parts))
    text = text.replace(">!", "").replace("!<", "")
    return terminal_text(text)


def narration_text(title: str, body: str) -> str:
    title = plain_text(title)
    body = plain_text(body)
    if title and title[-1] not in ".!?":
        title += "."
    return f"{title}\n\n{body}".strip()
