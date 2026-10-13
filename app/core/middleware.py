"""ASGI request controls without thread/task-group wrappers around body streams."""
import threading
import time
from collections import OrderedDict, deque
from fastapi import HTTPException
from starlette.responses import JSONResponse

class RequestControls:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.windows = OrderedDict()
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        key = (scope.get('client') or ('unknown', 0))[0]
        auth = scope['path'].endswith(('/login', '/register'))
        limit = 10 if auth else self.settings.rate_limit
        with self.lock:
            now = time.monotonic()
            window_key = (key, auth)
            window = self.windows.setdefault(window_key, deque())
            while window and window[0] < now - 60:
                window.popleft()
            limited = len(window) >= limit
            if not limited:
                window.append(now)
            self.windows.move_to_end(window_key)
            while len(self.windows) > 10000:
                self.windows.popitem(last=False)
        if limited:
            return await JSONResponse({'detail':'Request rate limit exceeded'},status_code=429,
                                      headers={'Retry-After':'60'})(scope,receive,send)
        headers = dict(scope['headers'])
        length = headers.get(b'content-length')
        maximum = self.settings.max_upload_bytes + 1024 * 1024
        if length:
            try:
                length = int(length)
                if length < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({'detail':'Invalid Content-Length'},status_code=400)(scope,receive,send)
            if length > maximum:
                return await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body',b''))
            if received > maximum:
                raise HTTPException(413,'Request too large')
            return message
        async def controlled_send(message):
            if message['type']=='http.response.start':
                message['headers'] = list(message.get('headers',[])) + [
                    (b'x-content-type-options',b'nosniff'),(b'cache-control',b'no-store')]
            await send(message)
        await self.app(scope,limited_receive,controlled_send)
