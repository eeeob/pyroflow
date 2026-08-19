from typing import Final

# Attribute name under which the mark_bot_commands decorator stores its
# declarations on a Pyrogram Handler object. Namespaced because the handler
# belongs to Pyrogram, not to us.
BOT_COMMANDS_ATTR: Final[str] = "_pyroflow_bot_commands"


__all__ = (
    "BOT_COMMANDS_ATTR", 
)

