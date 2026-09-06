"""Small, synthetic Reddit-layout pages served only by the local test server."""

import json
from html import escape


def legacy_card(identity="abc0", body=None, *, extra="", title=None):
    content = (
        ""
        if body is None
        else (
            f'<div class="expando"><div class="usertext-body"><div class="md">{body}</div></div></div>'
        )
    )
    return (
        f'<div class="thing link self {extra}" data-type="link" data-fullname="t3_{identity}" '
        'data-score="123" data-domain="self.stories">'
        f'<a class="title">{escape(title or "Story " + identity)}</a>'
        f'<a class="comments" href="/r/stories/comments/{identity}/story/">comments</a>'
        f'<time datetime="2026-09-01T12:00:00Z"></time>{content}</div>'
    )


def modern_card(identity="abc0", body=None, *, extra="", title=None):
    content = "" if body is None else f'<div slot="text-body">{body}</div>'
    return (
        f'<shreddit-post post-id="t3_{identity}" post-type="text" score="123" '
        f'post-title="{escape(title or "Story " + identity, quote=True)}" '
        f'permalink="/r/stories/comments/{identity}/story/" '
        f'created-timestamp="2026-09-01T12:00:00Z" {extra}>{content}</shreddit-post>'
    )


def delayed(content, initial="Loading..."):
    # Test the actual browser's JavaScript execution and WebDriverWait, not just HTML parsing.
    return (
        f'<!doctype html><html><body><main id="fixture">{initial}</main>'
        '<script>setTimeout(() => {document.getElementById("fixture").innerHTML = '
        f"{json.dumps(content)};}}, 300);</script></body></html>"
    )
