"""Static type tests for `pyroflow.types.message`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InputRichMessage, Message as PyroMessage

    from pyroflow import CallbackQuery, Message
    from pyroflow.types import User

    async def _check_ask_message(message: Message, flag: bool) -> None:
        assert_type(await message.ask("hi"), Message)
        assert_type(await message.ask("hi", force_send=False), Message)
        assert_type(await message.ask("hi", force_send=True), Message)
        # A plain `bool` expands over the `Literal[False]` and `Literal[True]` overloads.
        assert_type(await message.ask("hi", force_send=flag), Message)

    async def _check_ask_message_pyrogram_arguments(message: Message) -> None:
        await message.ask("hi", True, disable_notification=True, listen_timeout=5)
        await message.ask("hi", parse_mode=None)
        await message.ask("hi", True, disable_notification="yes")  # ty: ignore[no-matching-overload]

    async def _check_ask_message_rejects(message: Message) -> None:
        await message.ask(1)  # ty: ignore[invalid-argument-type]

    async def _check_ask_message_rich(message: Message, rich: InputRichMessage) -> None:
        assert_type(await message.ask_rich(rich), Message)
        assert_type(await message.ask_rich(rich, force_send=True), Message)

    async def _check_ask_message_rich_rejects(message: Message) -> None:
        await message.ask_rich("hi")  # ty: ignore[invalid-argument-type]

    async def _check_ask_callback_query(message: Message) -> None:
        assert_type(await message.ask_callback_query("hi"), CallbackQuery)
        assert_type(await message.ask_callback_query("hi", force_send=True), CallbackQuery)

    async def _check_ask_callback_query_rejects(message: Message) -> None:
        await message.ask_callback_query(1)  # ty: ignore[invalid-argument-type]

    async def _check_ask_callback_query_rich(message: Message, rich: InputRichMessage) -> None:
        assert_type(await message.ask_callback_query_rich(rich), CallbackQuery)
        assert_type(await message.ask_callback_query_rich(rich, force_send=True), CallbackQuery)

    async def _check_ask_callback_query_rich_rejects(message: Message) -> None:
        await message.ask_callback_query_rich("hi")  # ty: ignore[invalid-argument-type]

    async def _check_respond(message: Message) -> None:
        assert_type(await message.respond("hi"), PyroMessage | None)
        await message.respond("hi", parse_mode=None)

    async def _check_respond_rejects_what_only_one_side_takes(message: Message) -> None:
        await message.respond("hi", disable_notification=True)  # ty: ignore[unknown-argument]
        await message.respond("hi", rich_message=None)  # ty: ignore[unknown-argument]

    def _check_related_objects_are_the_patched_classes(message: Message) -> None:
        assert_type(message.from_user, User | None)
        assert_type(message.receiver_user, User | None)
        assert_type(message.reply_to_message, Message | None)
        assert_type(message.pinned_message, Message | None)
        assert_type(message.new_chat_members, list[User] | None)
        assert_type(message.via_bot, User | None)
        if message.reply_to_message is not None:
            assert_type(message.reply_to_message.editable, bool)
