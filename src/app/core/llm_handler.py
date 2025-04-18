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
    messages: List[Dict[str, str]], model_name: str = settings.LLM_MODEL
) -> AsyncGenerator[str, None]:
    """
    Sends messages list to the specified LLM via litellm and streams the response chunks.

    Args:
        messages: A list of message dictionaries (e.g., system, user roles).
        model_name: The LiteLLM model string (e.g., 'ollama/model', 'gemini/model', 'gpt-4o').
                    Defaults to settings.LLM_MODEL.

    Yields:
        Chunks of the text content generated by the LLM.

    Raises:
        LLMNotAvailableError: If the LLM call fails.
        ValueError: If messages list is empty.
    """
    if not messages:
        raise ValueError("Messages list cannot be empty.")

    llm_kwargs = {
        "timeout": settings.LLM_TIMEOUT,
    }
    if settings.LLM_API_KEY:
        llm_kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_API_BASE_URL:
        llm_kwargs["api_base"] = settings.LLM_API_BASE_URL

    logger.debug(f"Attempting streaming LLM call to model: {model_name}")
    logger.debug(f"LLM API Base: {settings.LLM_API_BASE_URL or 'Default'}")
    logger.debug(f"LLM API Key Provided: {bool(settings.LLM_API_KEY)}")
    logger.debug(f"LLM messages payload: {messages}")
    logger.debug(f"LiteLLM kwargs: { {k: v for k, v in llm_kwargs.items() if k != 'api_key'} }") # Don't log key

    try:
        response_stream = await litellm.acompletion(
            model=model_name,
            messages=messages,
            stream=True,
            **llm_kwargs, # Pass api_key, api_base, timeout etc.
        )

        async for chunk in response_stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    except httpx.ConnectError as e:
        logger.error(f"Connection error calling LLM ({model_name}): {e}")
        raise LLMNotAvailableError(f"Could not connect to LLM service at {settings.LLM_API_BASE_URL or 'default endpoint'}") from e
    except litellm.exceptions.AuthenticationError as e:
         logger.error(f"LiteLLM Authentication Error ({model_name}): {e}")
         raise LLMNotAvailableError(f"LLM authentication failed. Check API key.") from e
    except litellm.exceptions.APIConnectionError as e:
        logger.error(f"LiteLLM API connection error ({model_name}): {e}")
        raise LLMNotAvailableError(f"API connection error to {settings.LLM_API_BASE_URL or 'default endpoint'}") from e
    except litellm.exceptions.Timeout as e:
        logger.error(f"LiteLLM timeout error ({model_name}): {e}")
        raise LLMNotAvailableError(f"LLM call timed out after {settings.LLM_TIMEOUT}s") from e
    except litellm.exceptions.APIError as e: # Catch generic API errors (like rate limits, bad requests)
        logger.error(f"LiteLLM API error ({model_name}, status {e.status_code}): {e.message}")
        raise LLMNotAvailableError(f"LLM API error ({e.status_code}): {e.message}") from e
    except Exception as e:
        logger.exception(f"An unexpected error occurred during LLM call ({model_name}): {e}")
        raise LLMNotAvailableError(f"An unexpected error occurred: {e}") from e

    logger.debug("LLM stream finished.")


async def call_llm(
    messages: List[Dict[str, str]], model_name: str = settings.LLM_MODEL
) -> str:
    """
    Sends messages list to the specified LLM via litellm and returns the complete response.

    Aggregates the streamed response.

    Args:
        messages: A list of message dictionaries (e.g., system, user roles).
        model_name: The LiteLLM model string. Defaults to settings.LLM_MODEL.

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
