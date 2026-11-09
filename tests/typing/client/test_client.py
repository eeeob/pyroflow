"""Static type tests for ``pyroflow.client.client``."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pyroflow.models import AskAgain
    from typing_extensions import assert_type

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage, ReplyKeyboardRemove

    from pyroflow import CallbackQuery, Client, Message
    from pyroflow.enums import WorkersPolicy

    def _check_setup_pyroflow(client: Client) -> None:
        policy = WorkersPolicy.REJECT
        assert_type(client.setup_pyroflow(workers_policy=policy), Client)
        assert_type(client.setup_pyroflow(ask_context_message=False), Client)
        assert_type(client.setup_pyroflow(), Client)

    async def _check_ask_message(client: Client) -> None:
        assert_type(await client.ask(1, "hi"), Message)
        assert_type(await client.ask("chat", "hi", listen_timeout=5), Message)
        assert_type(await client.ask(1, "hi", 5), Message)
        assert_type(await client.ask(1, "hi", edit_message_id=5), Message)

    async def _check_ask_message_pyrogram_arguments(client: Client) -> None:
        await client.ask(1, "hi", disable_notification=True, listen_timeout=5)
        await client.ask(1, "hi", ephemeral_message_parameters=None, reply_to_message_id=3)
        await client.ask(1, "hi", 5, parse_mode=None)
        await client.ask(1, "hi", disable_notification="yes")  # ty: ignore[invalid-argument-type]

    async def _check_ask_message_rejects(client: Client) -> None:
        await client.ask(1, "hi", "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_message_rich(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich), Message)
        assert_type(await client.ask_rich(1, rich, 5), Message)

    async def _check_ask_message_rich_rejects(client: Client, rich: InputRichMessage) -> None:
        await client.ask_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_rich(1, rich, "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_callback_query(client: Client) -> None:
        assert_type(await client.ask_callback_query(1, "hi"), CallbackQuery)
        assert_type(await client.ask_callback_query(1, "hi", 5), CallbackQuery)

    async def _check_ask_callback_query_rejects(client: Client) -> None:
        await client.ask_callback_query(1, "hi", "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_callback_query_rich(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_callback_query_rich(1, rich), CallbackQuery)
        assert_type(await client.ask_callback_query_rich(1, rich, 5), CallbackQuery)

    async def _check_ask_callback_query_rich_rejects(
        client: Client, rich: InputRichMessage
    ) -> None:
        await client.ask_callback_query_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_callback_query_rich(1, rich, "5")  # ty: ignore[no-matching-overload]

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

    async def _check_ask_until(client: Client, passes: Filter) -> None:
        assert_type(await client.ask_until(1, "hi", parse=_accepts), Message)
        # ty keeps the coroutine in the result of an async `parse`, so only the call is checked.
        await client.ask_until(1, "hi", 5, parse=_asks_again)
        assert_type(await client.ask_until(1, "hi", parse=_parses), int)
        await client.ask_until(
            "chat",
            "hi",
            edit_message_id=5,
            parse=_replaces,
            attempts=3,
            listen_user_id=7,
            listen_filters=passes,
            listen_strict=True,
            listen_timeout=1.5,
            reply_markup=None,
        )
        await client.ask_until(1, "hi", parse=_accepts, disable_notification=True)

    async def _check_ask_until_rejects(client: Client, remove: ReplyKeyboardRemove) -> None:
        await client.ask_until(1, "hi")  # ty: ignore[no-matching-overload]
        await client.ask_until(1, "hi", parse=_accepts, attempts="3")  # ty: ignore[invalid-argument-type]
        # Retries send with the edit arguments, so an edit cannot take a send-only keyboard.
        await client.ask_until(1, "hi", 5, parse=_accepts, reply_markup=remove)  # ty: ignore[no-matching-overload]

    async def _check_ask_rich_until(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich_until(1, rich, parse=_accepts_rich), Message)
        assert_type(await client.ask_rich_until(1, rich, 5, parse=_accepts_rich), Message)

    async def _check_ask_rich_until_rejects(client: Client, rich: InputRichMessage) -> None:
        await client.ask_rich_until(1, "hi", parse=_accepts_rich)  # ty: ignore[invalid-argument-type]

    async def _check_ask_callback_query_until(client: Client) -> None:
        assert_type(
            await client.ask_callback_query_until(1, "hi", parse=_accepts_press), CallbackQuery
        )
        assert_type(
            await client.ask_callback_query_until(1, "hi", 5, parse=_accepts_press), CallbackQuery
        )

    async def _check_ask_callback_query_until_rejects(
        client: Client, remove: ReplyKeyboardRemove
    ) -> None:
        await client.ask_callback_query_until(1, "hi")  # ty: ignore[no-matching-overload]
        await client.ask_callback_query_until(1, "hi", parse=_accepts)  # ty: ignore[invalid-argument-type]
        await client.ask_callback_query_until(1, "hi", 5, parse=_accepts_press, reply_markup=remove)  # ty: ignore[no-matching-overload]

    async def _check_ask_callback_query_rich_until(client: Client, rich: InputRichMessage) -> None:
        assert_type(
            await client.ask_callback_query_rich_until(1, rich, parse=_accepts_rich_press),
            CallbackQuery,
        )
        assert_type(
            await client.ask_callback_query_rich_until(1, rich, 5, parse=_accepts_rich_press),
            CallbackQuery,
        )

    async def _check_ask_callback_query_rich_until_rejects(
        client: Client, rich: InputRichMessage
    ) -> None:
        await client.ask_callback_query_rich_until(1, "hi", parse=_accepts_rich_press)  # ty: ignore[invalid-argument-type]
        await client.ask_callback_query_rich_until(1, rich)  # ty: ignore[no-matching-overload]
