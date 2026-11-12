"""Static type tests for `pyroflow.types.message`."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pyroflow.models import AskAgain
    from typing_extensions import assert_type

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage, Message as PyroMessage, ReplyKeyboardRemove

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

    def _accepts(answer: Message, kw: dict[str, Any]) -> Message:
        return answer

    def _parses(answer: Message, kw: dict[str, Any]) -> AskAgain[str] | int:
        return 1

    async def _asks_again(answer: Message, kw: dict[str, Any]) -> AskAgain[str] | Message:
        return AskAgain("again")

    def _replaces(answer: Message, kw: dict[str, Any]) -> AskAgain[str]:
        return AskAgain("again", kw)

    def _accepts_rich(answer: Message, kw: dict[str, Any]) -> AskAgain[InputRichMessage] | Message:
        return answer

    def _accepts_press(press: CallbackQuery, kw: dict[str, Any]) -> CallbackQuery:
        return press

    def _accepts_rich_press(
        press: CallbackQuery, kw: dict[str, Any]
    ) -> AskAgain[InputRichMessage] | CallbackQuery:
        return press

    async def _check_ask_until(message: Message, passes: Filter, flag: bool) -> None:
        assert_type(await message.ask_until("hi", parse=_accepts), Message)
        # ty keeps the coroutine in the result of an async `parse`, so only the call is checked.
        await message.ask_until("hi", True, parse=_asks_again)
        assert_type(await message.ask_until("hi", parse=_parses), int)
        assert_type(await message.ask_until("hi", flag, parse=_accepts), Message)
        await message.ask_until(
            "hi",
            force_send=True,
            parse=_replaces,
            attempts=3,
            listen_user_id=7,
            listen_filters=passes,
            listen_strict=True,
            listen_timeout=1.5,
            disable_notification=True,
        )

    async def _check_ask_until_rejects(message: Message, remove: ReplyKeyboardRemove) -> None:
        await message.ask_until("hi")  # ty: ignore[no-matching-overload]
        await message.ask_until("hi", parse=_accepts, attempts="3")  # ty: ignore[invalid-argument-type]
        # Retries reply with the edit arguments, so an edit cannot take a reply-only keyboard.
        await message.ask_until("hi", parse=_accepts, reply_markup=remove)  # ty: ignore[invalid-argument-type]

    async def _check_ask_rich_until(message: Message, rich: InputRichMessage) -> None:
        assert_type(await message.ask_rich_until(rich, parse=_accepts_rich), Message)
        assert_type(await message.ask_rich_until(rich, True, parse=_accepts_rich), Message)

    async def _check_ask_rich_until_rejects(message: Message, rich: InputRichMessage) -> None:
        await message.ask_rich_until("hi", parse=_accepts_rich)  # ty: ignore[invalid-argument-type]

    async def _check_ask_callback_query_until(message: Message) -> None:
        assert_type(
            await message.ask_callback_query_until("hi", parse=_accepts_press), CallbackQuery
        )
        assert_type(
            await message.ask_callback_query_until("hi", True, parse=_accepts_press), CallbackQuery
        )

    async def _check_ask_callback_query_until_rejects(message: Message) -> None:
        await message.ask_callback_query_until("hi")  # ty: ignore[no-matching-overload]
        await message.ask_callback_query_until("hi", parse=_accepts)  # ty: ignore[invalid-argument-type]

    async def _check_ask_callback_query_rich_until(
        message: Message, rich: InputRichMessage
    ) -> None:
        assert_type(
            await message.ask_callback_query_rich_until(rich, parse=_accepts_rich_press),
            CallbackQuery,
        )
        assert_type(
            await message.ask_callback_query_rich_until(rich, True, parse=_accepts_rich_press),
            CallbackQuery,
        )

    async def _check_ask_callback_query_rich_until_rejects(
        message: Message, rich: InputRichMessage
    ) -> None:
        await message.ask_callback_query_rich_until("hi", parse=_accepts_rich_press)  # ty: ignore[invalid-argument-type]
        await message.ask_callback_query_rich_until(rich)  # ty: ignore[no-matching-overload]

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
