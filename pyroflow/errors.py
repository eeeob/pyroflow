class ListenerError(Exception):
    """Listener error"""

    def __init__(self, value = None):
        self.value = value
        # Subclasses carry their message as the class docstring. Fall back to
        # the class name if one is missing — or was shadowed by a statement
        # placed above it — so a malformed subclass degrades to a plain
        # message instead of raising AttributeError from the constructor.
        template = self.__class__.__doc__ or (self.__class__.__name__ + " {value}")
        super().__init__(template.format(value=value))


class ListenerCancelled(ListenerError):
    """UpdateListener {value} was cancelled"""

    def __init__(self, value = None, is_duplicate: bool = False):
        super().__init__(value)
        self.is_duplicate = is_duplicate

class ListenerTimeout(ListenerError):
    """UpdateListener {value} timed out"""

class ListenerAlreadyExists(ListenerError):
    """UpdateListener already exists for key {value}"""

class UnresolvedUpdate(ListenerError):
    """UnresolvedUpdate {value}"""

class UnhandledUpdate(ListenerError):
    """UnhandledUpdate {value}"""
