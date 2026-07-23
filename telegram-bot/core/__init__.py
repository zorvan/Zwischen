"""Transport-neutral core abstractions.

Nothing in this package may import ``telegram``. It holds the types the domain
services talk in, so the same service can serve a bot, an HTTP API or a mobile
push without knowing which is on the other end.
"""
