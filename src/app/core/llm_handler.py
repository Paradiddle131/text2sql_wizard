import litellm
import httpx
import logging
from typing import AsyncGenerator, List, Dict
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMNotAvailableError(Exception):
    """Custom exception for when the LLM service is unreachable or fails."""

    pass


async def stream_llm_response(
    messages: List[Dict[str, str]], model_name: str = settings.OLLAMA_MODEL_NAME
) -> AsyncGenerator[str, None]:
    """
    Sends messages list to the LLM via litellm and streams the response chunks.

    Args:
        messages: A list of message dictionaries (e.g., system, user roles).
        model_name: The specific Ollama model name to use.

    Yields:
        Chunks of the text content generated by the LLM.

    Raises:
        LLMNotAvailableError: If the LLM call fails.
        ValueError: If messages list is empty.
    """
    if not messages:
        raise ValueError("Messages list cannot be empty.")

    logger.debug(
        f"Attempting streaming LLM call to model: ollama/{model_name} "
        f"at API base: {settings.OLLAMA_API_BASE_URL}"
    )
    logger.debug(f"LLM messages payload: {messages}")

    try:
        response_stream = await litellm.acompletion(
            model=f"ollama/{model_name}",
            messages=messages,
            api_base=settings.OLLAMA_API_BASE_URL,
            stream=True,
            timeout=settings.LLM_TIMEOUT,
        )

        async for chunk in response_stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    except httpx.ConnectError as e:
        logger.error(f"Connection error calling LLM: {e}")
        raise LLMNotAvailableError(f"Could not connect to LLM service") from e
    except litellm.exceptions.APIConnectionError as e:
        logger.error(f"LiteLLM API connection error: {e}")
        raise LLMNotAvailableError(f"API connection error") from e
    except litellm.exceptions.Timeout as e:
        logger.error(f"LiteLLM timeout error: {e}")
        raise LLMNotAvailableError(f"LLM call timed out") from e
    except litellm.exceptions.APIError as e:
        logger.error(f"LiteLLM API error (status {e.status_code}): {e.message}")
        raise LLMNotAvailableError(f"LLM API error ({e.status_code})") from e
    except Exception as e:
        logger.exception(f"An unexpected error occurred during LLM call: {e}")
        raise LLMNotAvailableError(f"An unexpected error occurred: {e}") from e

    logger.debug("LLM stream finished.")


async def call_llm(
    messages: List[Dict[str, str]], model_name: str = settings.OLLAMA_MODEL_NAME
) -> str:
    """
    Sends messages list to the LLM via litellm and returns the complete response.

    Aggregates the streamed response.

    Args:
        messages: A list of message dictionaries (e.g., system, user roles).
        model_name: The specific Ollama model name to use.

    Returns:
        The complete text content generated by the LLM.

    Raises:
        LLMNotAvailableError: If the LLM call fails.
    """
    full_response = ""
    try:
        async for chunk in stream_llm_response(messages, model_name):
            full_response += chunk
    except LLMNotAvailableError:
        raise
    except Exception as e:
        logger.exception(f"An unexpected error occurred aggregating LLM stream: {e}")
        raise LLMNotAvailableError(f"Failed to aggregate LLM stream: {e}") from e

    if not full_response:
        logger.warning("LLM returned an empty response after streaming.")

    logger.debug("LLM call (aggregated from stream) completed.")
    return full_response
