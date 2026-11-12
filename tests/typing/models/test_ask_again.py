"""Static type tests for `pyroflow.models.ask_again`."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow import Message
    from pyroflow.models import AskAgain, AskParser

    def _accepts(answer: Message, kw: dict[str, Any]) -> int:
        return 1

    async def _asks_again(answer: Message, kw: dict[str, Any]) -> AskAgain[str] | int:
        return AskAgain("again")

    def _replaces(answer: Message, kw: dict[str, Any]) -> AskAgain[str]:
        return AskAgain("again", kw)

    def _wrong_question(answer: Message, kw: dict[str, Any]) -> AskAgain[int]:
        return AskAgain(1)

    def _wrong_result(answer: Message, kw: dict[str, Any]) -> str:
        return "no"

    def _takes_parser(parse: AskParser[Message, str, int]) -> None: ...

    def _check_ask_parser() -> None:
        _takes_parser(_accepts)
        _takes_parser(_asks_again)
        _takes_parser(_replaces)
        _takes_parser(_wrong_question)  # ty: ignore[invalid-argument-type]
        _takes_parser(_wrong_result)  # ty: ignore[invalid-argument-type]

    def _check_ask_again(again: AskAgain[str]) -> None:
        assert_type(again.question, str)
        assert_type(again.kw, dict[str, Any])
