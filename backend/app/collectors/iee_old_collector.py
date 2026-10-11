"""Iran Energy Exchange (IEE) - old site collector.

Deliberately left unimplemented - investigation concluded there is
nothing distinct here to implement against. The original assumption (see
docs/DATA_SOURCES.md history) was that oldsite.iee.ir would be a legacy
ASP.NET WebForms app with server-rendered HTML tables, requiring an
HTML-scraping collector. That was wrong: its HTML is byte-for-byte the
same React SPA shell as newsite.iee.ir (same title, same org/schema.org
metadata), and its JS bundle (`main.73cd4015.js`) contains the exact same
API base URL, `https://webapi.iee.ir/api`, as the new site's bundle.

The only real difference is the `Last-Modified` header: oldsite's build
is from 2026-06-29, newsite's is same-day-fresh - so `oldsite.iee.ir` is
simply an older, stale deployment of the identical app, calling the same
live backend that `IEENewCollector` already polls. There is no separate
dataset to collect here. Building a second collector against it would
only add duplicate load on the same API and a second, less-fresh path to
the same numbers, plus the risk that this stale build disappears or
starts erroring with no notice.

`fetch_raw`'s return type is left as `object` (not assumed JSON) in case
a future investigation of a *different* legacy endpoint proves this
wrong, but for now `configured = False` is correct, not just cautious.
"""

from typing import Any

import httpx

from app.collectors.base import BaseCollector, NormalizedQuote
from app.core.config import get_settings

settings = get_settings()


class IEEOldCollector(BaseCollector):
    source_id = "iee_old"
    name = "Iran Energy Exchange (old site)"
    base_url = settings.IEE_OLD_BASE_URL
    configured = False

    async def fetch_raw(self, client: httpx.AsyncClient) -> Any:
        raise NotImplementedError("IEE old-site endpoint not yet discovered - see docs/DATA_SOURCES.md")

    def parse(self, raw: Any) -> list[NormalizedQuote]:
        return []
