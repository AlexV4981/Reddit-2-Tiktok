from __future__ import annotations

import math
from pathlib import Path

from .config import Config
from .text import terminal_text
from .tts import Word, validate_words


def timestamp(centiseconds: int) -> str:
    hours, rest = divmod(centiseconds, 360_000)
    minutes, rest = divmod(rest, 6000)
    seconds, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centis:02}"


def caption_text(value: str) -> str:
    # ASS uses braces/backslashes as executable formatting; Reddit text must stay literal.
    return terminal_text(value).replace("\\", "／").replace("{", "｛").replace("}", "｝")


def write_ass(words: list[Word], path: Path, config: Config, duration: float) -> None:
    validate_words(words, duration)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.width}
PlayResY: {config.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{config.font},{config.font_size},&H0000FFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,5,2,5,70,70,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for index, word in enumerate(words):
        text = caption_text(word.text)
        next_start = words[index + 1].start if index + 1 < len(words) else duration
        start = int(word.start * 100)
        end = min(math.ceil(word.end * 100), int(next_start * 100), int(duration * 100))
        if end <= start:
            continue  # ASS has 10ms precision; never overlap adjacent word events.
        # Fit unusually long tokens within the central 80% of the portrait canvas.
        size = min(config.font_size, max(12, int(config.width * 0.8 / max(1, len(text)))))
        style = (
            f"{{\\an5\\pos({config.width // 2},{int(config.height * config.caption_y)})"
            f"\\fs{size}\\fscx90\\fscy90\\t(0,60,\\fscx100\\fscy100)}}"
        )
        lines.append(
            f"Dialogue: 0,{timestamp(start)},{timestamp(end)},Word,,0,0,0,,{style}{text}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")
