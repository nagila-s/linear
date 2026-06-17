import asyncio

from src.services.dorina_client import DorinaService


class DorinaClient:
    """
    Compat layer do worker v2 para o cliente Dorina existente no Linear.
    """

    def __init__(self):
        self._service = DorinaService()

    async def describe(
        self,
        image_url: str,
        context: str = "",
        prompt_version: str = "v1",
        braille: bool = False,
    ) -> dict:
        response = await asyncio.to_thread(
            self._service.describe_figure,
            image_url=image_url,
            isbn="",
            context=context,
            prompt_version=prompt_version,
            image_id=0,
            document_id=0,
        )
        return response
