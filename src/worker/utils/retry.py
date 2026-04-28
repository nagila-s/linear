import asyncio
import functools

from src.worker.utils.logger import get_logger

logger = get_logger(__name__)


def retry_async(max_attempts: int = 3, base_delay: float = 2.0):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as error:
                    last_error = error
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} falhou apos {max_attempts} tentativas",
                            error=str(error),
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"{func.__name__} tentativa {attempt}/{max_attempts} falhou, retry em {delay:.0f}s",
                        error=str(error),
                    )
                    await asyncio.sleep(delay)
            raise last_error

        return wrapper

    return decorator
