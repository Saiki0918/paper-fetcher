from typing import Protocol

from app.schemas.paper import Paper


class PaperSource(Protocol):
    name: str

    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        """Return normalized papers and the total number of matching records."""
