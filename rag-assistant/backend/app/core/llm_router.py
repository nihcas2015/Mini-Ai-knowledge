import logging
import asyncio
from typing import AsyncGenerator
import google.generativeai as genai
from groq import AsyncGroq
from openai import AsyncOpenAI

from app.config import settings
from app.core.notifications import notify_admin

logger = logging.getLogger(__name__)

class LLMRouter:
    def __init__(self):
        self._dead_keys: set[str] = set()
        self._key_indices: dict[str, int] = {
            "groq": 0,
            "openrouter": 0,
            "gemini": 0
        }

    async def generate(self, system_prompt: str, user_message: str, stream: bool = False) -> AsyncGenerator | str:
        if stream:
            return await self.generate_stream(system_prompt, user_message)

        providers = [
            ("groq", settings.groq_keys, self._try_groq),
            ("openrouter", settings.openrouter_keys, self._try_openrouter),
            ("gemini", settings.gemini_keys, self._try_gemini)
        ]

        for provider_name, keys, attempt_func in providers:
            if not keys:
                continue

            start_index = self._key_indices[provider_name]
            num_keys = len(keys)
            
            for i in range(num_keys):
                idx = (start_index + i) % num_keys
                key = keys[idx]
                
                if key in self._dead_keys:
                    continue
                    
                self._key_indices[provider_name] = (idx + 1) % num_keys
                
                try:
                    result = await asyncio.wait_for(
                        attempt_func(key, system_prompt, user_message, stream=False),
                        timeout=settings.LLM_TIMEOUT
                    )
                    logger.info(f"Request served by {provider_name}_key_{idx+1}")
                    return result
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout with {provider_name}_key_{idx+1}")
                except Exception as e:
                    err_msg = str(e).lower()
                    if "401" in err_msg or "403" in err_msg or "unauthorized" in err_msg or "invalid_api_key" in err_msg:
                        logger.error(f"Key invalid (401/403): {provider_name}_key_{idx+1}")
                        self._dead_keys.add(key)
                        await notify_admin("KEY_INVALID", f"{provider_name}_key_{idx+1} returned 401/403 and was marked dead.")
                    elif "429" in err_msg or "rate" in err_msg:
                        logger.warning(f"Rate limited (429) on {provider_name}_key_{idx+1}")
                    else:
                        logger.warning(f"Error with {provider_name}_key_{idx+1}: {e}")

        await notify_admin("LLM_TOTAL_FAILURE", "All 9 LLM attempts failed.")
        return "The assistant is temporarily unavailable. Please try again in a moment."

    async def generate_stream(self, system_prompt: str, user_message: str) -> AsyncGenerator[str | dict, None]:
        providers = [
            ("groq", settings.groq_keys, self._try_groq),
            ("openrouter", settings.openrouter_keys, self._try_openrouter),
            ("gemini", settings.gemini_keys, self._try_gemini)
        ]

        for provider_name, keys, attempt_func in providers:
            if not keys:
                continue

            start_index = self._key_indices[provider_name]
            num_keys = len(keys)
            
            for i in range(num_keys):
                idx = (start_index + i) % num_keys
                key = keys[idx]
                
                if key in self._dead_keys:
                    continue
                    
                self._key_indices[provider_name] = (idx + 1) % num_keys
                
                try:
                    stream_gen = await asyncio.wait_for(
                        attempt_func(key, system_prompt, user_message, stream=True),
                        timeout=settings.LLM_TIMEOUT
                    )
                    logger.info(f"Streaming request served by {provider_name}_key_{idx+1}")
                    
                    # Yield provider info first, then tokens
                    yield {"provider": provider_name}
                    async for chunk in stream_gen:
                        yield chunk
                    return
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout with {provider_name}_key_{idx+1}")
                except Exception as e:
                    err_msg = str(e).lower()
                    if "401" in err_msg or "403" in err_msg or "unauthorized" in err_msg or "invalid_api_key" in err_msg:
                        logger.error(f"Key invalid (401/403): {provider_name}_key_{idx+1}")
                        self._dead_keys.add(key)
                        await notify_admin("KEY_INVALID", f"{provider_name}_key_{idx+1} returned 401/403 and was marked dead.")
                    elif "429" in err_msg or "rate" in err_msg:
                        logger.warning(f"Rate limited (429) on {provider_name}_key_{idx+1}")
                    else:
                        logger.warning(f"Error with {provider_name}_key_{idx+1}: {e}")

        await notify_admin("LLM_TOTAL_FAILURE", "All 9 LLM streaming attempts failed.")
        yield {"provider": "none"}
        yield "The assistant is temporarily unavailable. Please try again in a moment."

    async def _try_groq(self, key: str, system_prompt: str, user_message: str, stream: bool):
        client = AsyncGroq(api_key=key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            stream=stream
        )
        if stream:
            async def gen():
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            return gen()
        else:
            return response.choices[0].message.content

    async def _try_openrouter(self, key: str, system_prompt: str, user_message: str, stream: bool):
        client = AsyncOpenAI(api_key=key, base_url=settings.OPENROUTER_BASE_URL)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        response = await client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=messages,
            stream=stream
        )
        if stream:
            async def gen():
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            return gen()
        else:
            return response.choices[0].message.content

    async def _try_gemini(self, key: str, system_prompt: str, user_message: str, stream: bool):
        # NOTE: genai.configure() sets global SDK state. Under real concurrent
        # requests this could race with another in-flight Gemini call using a
        # different key. Acceptable for this project's single-instance,
        # low-concurrency deployment target (§9), but documented here as a
        # known limitation rather than a silent risk.
        genai.configure(api_key=key)
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system_prompt
        )
        response = await asyncio.to_thread(
            model.generate_content,
            user_message,
            stream=stream
        )
        if stream:
            # `response` here is a synchronous, blocking generator from the
            # google-generativeai SDK. Iterating it directly inside an async
            # generator would block the event loop on every chunk. Pull each
            # chunk via asyncio.to_thread so other requests can still be
            # served while we wait on the network.
            async def gen():
                iterator = iter(response)
                while True:
                    chunk = await asyncio.to_thread(next, iterator, None)
                    if chunk is None:
                        break
                    if chunk.text:
                        yield chunk.text
            return gen()
        else:
            return response.text

_llm_router = LLMRouter()

def get_llm_router() -> LLMRouter:
    return _llm_router
