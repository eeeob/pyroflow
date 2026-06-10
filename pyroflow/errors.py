class ListenerError(Exception):
    def __init__(self, value = None):
        self.value = value
        super().__init__(self.__class__.__doc__.format(value=value))


class ListenerCancelled(ListenerError):
    """UpdateListener {value} was cancelled"""

class ListenerTimeout(ListenerError):
    """UpdateListener {value} timed out"""

class ListenerAlreadyExists(ListenerError):
    """UpdateListener already exists for key {value}"""

class UnresolvedUpdate(ListenerError):
    """UnresolvedUpdate {value}"""

class UnhandledUpdate(ListenerError):
    """UnhandledUpdate {value}"""