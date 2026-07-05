"""
Shared slowapi Limiter instance.

Lives in its own module (rather than main.py) so router modules can import
it for their @limiter.limit(...) decorators without a circular import
(main.py imports the routers, so the routers can't import the limiter back
from main.py).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
