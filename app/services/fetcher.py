import aiohttp

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
)


async def fetch_html(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"User-Agent": DEFAULT_USER_AGENT}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                return ""
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return ""
            return await response.text(errors="ignore")
