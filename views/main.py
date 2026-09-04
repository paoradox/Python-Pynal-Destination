from pathlib import Path

import flet as ft

from models import CheckpointRepository
from views.checkpoints import CheckpointView


class Pynal_DestinationApp:
    def __init__(self, page: ft.Page):
        self._page = page

    async def start(self) -> None:
        self._page.title = "Pynal Destination"
        if self._page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
            documents_directory = await self._page.storage_paths.get_application_documents_directory()
            database_path = Path(documents_directory) / "travel_checkpoints.db"
        else:
            database_path = Path("travel_checkpoints.db")

        repository = CheckpointRepository(database_path)
        view = CheckpointView(self._page, repository)
        await view.initialize()
        self._page.add(view.control())


async def main(page: ft.Page):
    app = Pynal_DestinationApp(page)
    await app.start()


ft.run(main)