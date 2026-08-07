from __future__ import annotations

from typing import Any, Iterable


HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3


def _last_hangul_syllable(value: str) -> str:
    stripped = value.rstrip()
    if not stripped:
        raise ValueError("조사를 붙일 빈 문자열은 허용되지 않습니다.")
    last = stripped[-1]
    codepoint = ord(last)
    if not HANGUL_BASE <= codepoint <= HANGUL_END:
        raise ValueError(
            f"한글 음절로 끝나지 않아 조사를 결정할 수 없습니다: {value!r}"
        )
    return last


def has_final_consonant(value: str) -> bool:
    syllable = _last_hangul_syllable(value)
    return (ord(syllable) - HANGUL_BASE) % 28 != 0


def object_particle(value: str) -> str:
    return "을" if has_final_consonant(value) else "를"


def subject_particle(value: str) -> str:
    return "은" if has_final_consonant(value) else "는"


def attach_object(value: str) -> str:
    return f"{value}{object_particle(value)}"


def attach_subject(value: str) -> str:
    return f"{value}{subject_particle(value)}"


def validate_particle_tokens(tokens: Iterable[Any]) -> list[dict[str, str]]:
    """Validate 을/를 and 은/는 tokens emitted by a Korean tokenizer.

    The tokenizer is supplied by the caller so this small utility remains independent
    from a particular morphology package. Non-Hangul bases fail explicitly.
    """

    token_list = list(tokens)
    checked: list[dict[str, str]] = []
    for index, token in enumerate(token_list):
        form = str(token.form)
        tag = str(token.tag).split("-", 1)[0]
        if not ((tag == "JKO" and form in {"을", "를"}) or (tag == "JX" and form in {"은", "는"})):
            continue
        if index == 0:
            raise ValueError(f"조사 앞 형태소가 없습니다: {form}")
        base = str(token_list[index - 1].form)
        expected = object_particle(base) if tag == "JKO" else subject_particle(base)
        if form != expected:
            raise ValueError(
                f"조사 불일치: {base!r}+{form!r}, expected={expected!r}"
            )
        checked.append({"base": base, "particle": form, "tag": tag})
    return checked
