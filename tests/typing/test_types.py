"""Static type tests for ``pyroflow.types``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InputRichMessage

    from pyroflow import CallbackQuery, Message, Update

    async def _check_ask_edit(message: Message) -> None:
        assert_type(await message.ask("hi"), Message)  # ty: ignore[type-assertion-failure]  # bug: `Message.ask` returns the patch class, not the public `Message` (pyroflow/types.py:141-247)
        assert_type(await message.ask("hi", force_send=False), Message)  # ty: ignore[type-assertion-failure]  # bug: `Message.ask` returns the patch class, not the public `Message` (pyroflow/types.py:141-247)
        assert_type(await message.ask("hi", listen_update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_send(message: Message) -> None:
        assert_type(await message.ask("hi", force_send=True), Message)  # ty: ignore[type-assertion-failure]  # bug: `Message.ask` returns the patch class, not the public `Message` (pyroflow/types.py:141-247)
        assert_type(
            await message.ask("hi", force_send=True, listen_update_type=CallbackQuery),
            CallbackQuery,
        )

    async def _check_ask_bool_flag(message: Message, flag: bool) -> None:
        # A plain `bool` expands over the `Literal[False]` and `Literal[True]` overloads.
        await message.ask("hi", force_send=flag)

    async def _check_ask_rejects(message: Message) -> None:
        await message.ask("hi", listen_update_type=int)  # ty: ignore[no-matching-overload]
        await message.ask(1)  # ty: ignore[invalid-argument-type]

    async def _check_ask_rich_edit(message: Message, rich: InputRichMessage) -> None:
        assert_type(await message.ask_rich(rich), Message)  # ty: ignore[type-assertion-failure]  # bug: `Message.ask_rich` returns the patch class, not the public `Message`, like `Message.ask`
        assert_type(await message.ask_rich(rich, listen_update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_rich_send(message: Message, rich: InputRichMessage) -> None:
        assert_type(await message.ask_rich(rich, force_send=True), Message)  # ty: ignore[type-assertion-failure]  # bug: `Message.ask_rich` returns the patch class, not the public `Message`, like `Message.ask`
        assert_type(
            await message.ask_rich(rich, force_send=True, listen_update_type=CallbackQuery),
            CallbackQuery,
        )

    async def _check_ask_rich_rejects(message: Message, rich: InputRichMessage) -> None:
        await message.ask_rich(rich, listen_update_type=int)  # ty: ignore[no-matching-overload]
        await message.ask_rich("hi")  # ty: ignore[invalid-argument-type]

    def _check_with_ctx(message: Message, update: Update) -> None:
        assert_type(message.with_ctx(a=1), Message)
        assert_type(message.with_ctx({"a": 1}), Message)
        assert_type(message.with_ctx([("a", 1)], b=2), Message)
        assert_type(update.with_ctx(), Update)
        message.with_ctx(1)  # ty: ignore[no-matching-overload]
