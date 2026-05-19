import httpx
import os


class SessionManager:
    """Manages a shared httpx.AsyncClient for all HTTP-based engines.

    Call startup() during app lifespan init and shutdown() on teardown.
    The shared client provides connection pooling, redirect following,
    and a consistent User-Agent across all outbound requests.
    """

    _client: httpx.AsyncClient | None = None

    async def startup(self):
        # TODO: Add user-agent rotation (fake-useragent lib)
        # TODO: Add proxy rotation (read PROXY_LIST env var)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": os.getenv(
                    "DEFAULT_USER_AGENT",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36",
                )
            },
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )

    async def shutdown(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("SessionManager not started — call startup() first")
        return self._client


# Singleton instance — import and use across the app
session_manager = SessionManager()
