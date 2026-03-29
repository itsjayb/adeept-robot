#!/usr/bin/env python3
"""Natural-language commands for plane-locked drawing (pose saved on MCU with s)."""

from dataclasses import dataclass
import re
from typing import Optional, Tuple


@dataclass(frozen=True)
class CapabilityDecision:
    can_execute: bool
    response: str
    serial_command: Optional[str] = None
    should_execute: bool = False
    action: Optional[str] = None
    letter: Optional[str] = None


@dataclass(frozen=True)
class CapabilityContext:
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
        return "none"
    if len(upper) == 1:
        return upper[0]
    return ", ".join(upper[:-1]) + f", and {upper[-1]}"


def evaluate_command(command: str, context: CapabilityContext) -> CapabilityDecision:
    normalized = _normalize(command)
    supported_text = _format_supported_letters(context.supported_letters)
    if not normalized:
        return CapabilityDecision(
            can_execute=False,
            response="Say what you want, for example: draw the letter j with a single line.",
        )

    draw_requested = any(token in normalized for token in ("draw", "write", "trace"))
    learn_requested = any(token in normalized for token in ("learn", "teach", "practice"))
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

    if asks_help:
        return CapabilityDecision(
            can_execute=True,
            response=(
                "Save your drawing pose on the arm first: put the tip on the paper, then send s on the MCU "
                f"(or type s here). I only draw {supported_text} using that saved plane — small shoulder/elbow "
                "motion, no camera learning. Then say: draw the letter j with a single line."
            ),
        )

    if learn_requested:
        return CapabilityDecision(
            can_execute=True,
            response=(
                "Learning from the camera is turned off. Move the arm by hand or with keys until the tip "
                "touches where you want, send s to save that plane pose, then ask me to draw letter j."
            ),
            should_execute=False,
        )

    if not draw_requested and mentioned_letter is None:
        return CapabilityDecision(
            can_execute=False,
            response="Try: draw the letter j with a single line (after saving pose with s).",
        )

    if mentioned_letter is None:
        return CapabilityDecision(
            can_execute=False,
            response="Which letter? I only support drawing J from your saved plane pose.",
        )

    if mentioned_letter not in context.supported_letters:
        return CapabilityDecision(
            can_execute=False,
            response=f"I only draw {supported_text} from the saved plane pose right now.",
        )

    if draw_requested:
        if is_question and not asks_single_line:
            return CapabilityDecision(
                can_execute=True,
                response=(
                    f"Yes. After you save pose with s, I can run the plane-locked J stroke (serial y) "
                    f"for letter {mentioned_letter.upper()}."
                ),
                should_execute=False,
                action="plane_j",
                letter=mentioned_letter,
            )
        if asks_single_line and is_question:
            return CapabilityDecision(
                can_execute=True,
                response=(
                    f"Yes. Save tip position with s, then I will trace one J stroke on that plane "
                    f"for letter {mentioned_letter.upper()}."
                ),
                should_execute=False,
                action="plane_j",
                letter=mentioned_letter,
            )
        return CapabilityDecision(
            can_execute=True,
            response=f"Running plane-locked J for {mentioned_letter.upper()} (firmware command y).",
            should_execute=True,
            action="plane_j",
            letter=mentioned_letter,
        )

    return CapabilityDecision(
        can_execute=False,
        response="Try: draw the letter j with a single line.",
    )
