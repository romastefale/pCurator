import aiohttp


LINKPREVIEW_ENDPOINT = "https://api.linkpreview.net"


async def fetch_linkpreview(url: str, api_key: str | None) -> dict | None:
    if not api_key:
        return None

    params = {"key": api_key, "q": url}
    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(LINKPREVIEW_ENDPOINT, params=params) as response:
                if response.status >= 400:
                    return None
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    return None
                return data
    except Exception:
        return None
