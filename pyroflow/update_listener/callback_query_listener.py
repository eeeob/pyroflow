from typing import TYPE_CHECKING

from ..models import ListenerKey
from ..types import CallbackQuery

from .update_listener import UpdateListener



class CallbackQueryListener(UpdateListener[CallbackQuery]):
    __update_type__ = CallbackQuery

    if not TYPE_CHECKING:
        def __init__(
            self, 
            coordinator_factory = None, 
            duplicate_policy = None, 
            is_listenable_func = None, 
            extract_key_func = None, 
            **kw
            ):

            if is_listenable_func is None:
                is_listenable_func = self._is_listenable
            
            if extract_key_func is None:
                extract_key_func = self._extract_key

            super().__init__(coordinator_factory, duplicate_policy, is_listenable_func, extract_key_func, **kw)


    async def _is_listenable(self, update):
        m = update.message

        return (
            m is not None
            and m.chat is not None
        )

    async def _extract_key(self, update):
        m = update.message

        return ListenerKey(
            m.chat.id, 
            update.from_user.id, 
            m.id
        )
    

    async def on_unresolved(self, key, update):
        client = update._client
        m = update.message

        if not m or not getattr(m, "id", None):
            return await super().on_unresolved(key, update)

        try:
            m_listen = client.message_listen
        except KeyError:
            pass
        else:
            m_listeners = m_listen.listeners

            for sub in key.sub_keys():
                if listener := m_listeners.get(sub):
                    if isinstance(listener.meta, dict) and listener.meta.get("message_id") == m.id:
                        await m_listen.cancel(sub)
                    break

        return await super().on_unresolved(key, update)
        
            
        









