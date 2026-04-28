from src.services.dorina_client import DorinaService


class DorinaClient:
    """
    Compat layer do worker v2 para o cliente Dorina existente no Linear.
    """

    def __init__(self):
        self._service = DorinaService()

    async def describe(self, image_url: str, braille: bool = False) -> str:
        response = self._service.describe_figure(
            image_url=image_url,
            isbn="",
            context="",
            prompt_version="v1",
            image_id=0,
            document_id=0,
        )
        return str(response.get("description") or response.get("texto") or "")
