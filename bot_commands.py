#!/usr/bin/env python3
"""Natural-language capability checks for live-feed bot commands."""

from dataclasses import dataclass
import re
from typing import Optional, Tuple


@dataclass(frozen=True)
class CapabilityDecision:
    can_execute: bool
    response: str
    serial_command: Optional[str] = None
    should_execute: bool = False


@dataclass(frozen=True)
class CapabilityContext:
    live_feed_ready: bool
    good_view: bool
    supported_letters: Tuple[str, ...] = ("j",)


_LETTER_PATTERN = re.compile(r"\b(?:letter|character)\s+([a-z])\b")
_DRAW_PATTERN = re.compile(r"\b(?:draw|write|trace)\s+(?:the\s+)?(?:letter\s+)?([a-z])\b")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_letter(command: str) -> Optional[str]:
    match = _LETTER_PATTERN.search(command)
    if match:
        return match.group(1)

    match = _DRAW_PATTERN.search(command)
    if match:
        return match.group(1)

    if " letter j" in f" {command}" or "draw j" in command:
        return "j"
    return None


def _format_supported_letters(letters: Tuple[str, ...]) -> str:
    upper = [letter.upper() for letter in letters]
    if not upper:
        return "none yet"
    if len(upper) == 1:
        return upper[0]
    if len(upper) == 2:
        return f"{upper[0]} and {upper[1]}"
    return ", ".join(upper[:-1]) + f", and {upper[-1]}"


def evaluate_command(command: str, context: CapabilityContext) -> CapabilityDecision:
    normalized = _normalize(command)
    supported_text = _format_supported_letters(context.supported_letters)
    if not normalized:
        return CapabilityDecision(
            can_execute=False,
            response="I did not catch that. Please give me a drawing command.",
        )

    draw_requested = any(token in normalized for token in ("draw", "write", "trace"))
    mentioned_letter = _extract_letter(normalized)
    asks_single_line = any(
        phrase in normalized
        for phrase in ("single line", "single stroke", "one line", "one stroke")
    )
    is_question = (
        "can you" in normalized
        or "are you able" in normalized
        or "could you" in normalized
        or normalized.endswith("?")
    )
    asks_help = any(token in normalized for token in ("help", "what can you", "commands"))
    asks_view_status = any(
        token in normalized for token in ("camera", "live feed", "view", "see")
    )

    if asks_help:
        return CapabilityDecision(
            can_execute=True,
            response=(
                "I can check if I can draw something and explain why. "
                f"Right now I can draw letter {supported_text}. "
                "Try: 'draw the letter j with a single line' or "
                "'can you draw the letter a?'."
            ),
        )

    if asks_view_status and not draw_requested:
        if context.live_feed_ready and context.good_view:
            return CapabilityDecision(
                can_execute=True,
                response="Live feed looks good right now, so I can draw supported letters.",
            )
        if context.live_feed_ready:
            return CapabilityDecision(
                can_execute=False,
                response=(
                    "Live feed is on, but I do not have a good view of the target yet. "
                    "Show the marker clearly and I can draw."
                ),
            )
        return CapabilityDecision(
            can_execute=False,
            response="Live feed is not ready yet, so I cannot draw right now.",
        )

    if not draw_requested and mentioned_letter is None:
        return CapabilityDecision(
            can_execute=False,
            response=(
                "I am not sure what you want yet. I understand drawing requests like "
                "'draw the letter j with a single line'."
            ),
        )

    if mentioned_letter is None:
        return CapabilityDecision(
            can_execute=False,
            response="Please tell me which letter to draw.",
        )

    if mentioned_letter not in context.supported_letters:
        return CapabilityDecision(
            can_execute=False,
            response=(
                f"I cannot draw the letter {mentioned_letter.upper()} yet. "
                f"But I can draw letter {supported_text}."
            ),
        )

    if not context.live_feed_ready:
        return CapabilityDecision(
            can_execute=False,
            response=(
                "I cannot draw right now because the live feed is not ready. "
                "Check camera and serial connections."
            ),
        )

    if not context.good_view:
        return CapabilityDecision(
            can_execute=False,
            response=(
                "I cannot draw that yet because I do not have a good view. "
                "Center the target in the camera and try again."
            ),
        )

    if asks_single_line:
        if is_question:
            return CapabilityDecision(
                can_execute=True,
                response=(
                    "Yes, I can draw letter J with a single continuous stroke path "
                    "when the live view is good."
                ),
                serial_command="j",
                should_execute=False,
            )
        return CapabilityDecision(
            can_execute=True,
            response="Great, I have a good view. I will draw letter J with a single stroke now.",
            serial_command="j",
            should_execute=True,
        )

    if is_question:
        return CapabilityDecision(
            can_execute=True,
            response=f"Yes, I can draw letter {mentioned_letter.upper()}.",
            serial_command="j",
            should_execute=False,
        )

    return CapabilityDecision(
        can_execute=True,
        response=f"Great, I can draw letter {mentioned_letter.upper()} now.",
        serial_command="j",
        should_execute=True,
    )
