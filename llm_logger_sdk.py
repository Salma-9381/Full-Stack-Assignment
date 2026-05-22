"""
llm_logger_sdk.py
Lightweight SDK/middleware for capturing LLM inference metadata.
Drop-in wrapper around any provider (Anthropic, OpenAI, etc.)
"""

import time
import uuid
import httpx
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncGenerator
from dataclasses import dataclass, asdict


@dataclass
class InferenceMetadata:
    conversation_id: str
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_preview: str
    output_preview: str
    status: str
    error_message: Optional[str]
    timestamp: str
    request_id: str
    streaming: bool = False
    message_id: Optional[str] = None


class LLMLoggerSDK:
    """
    Lightweight SDK that wraps LLM API calls and sends
    inference metadata to the ingestion endpoint.
    """

    def __init__(
        self,
        ingestion_url: str = "http://localhost:8000/api/logs/ingest",
        api_key: Optional[str] = None,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        timeout: float = 5.0,
        fail_silently: bool = True,
    ):
        self.ingestion_url = ingestion_url
        self.api_key = api_key
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.fail_silently = fail_silently
        self._http = httpx.AsyncClient(timeout=timeout)

    async def send_log(self, metadata: InferenceMetadata):
        """Send inference log to the ingestion endpoint asynchronously."""
        try:
            payload = asdict(metadata)
            await self._http.post(self.ingestion_url, json=payload)
        except Exception as e:
            if not self.fail_silently:
                raise
            print(f"[LLMLoggerSDK] Failed to send log: {e}")

    async def call_anthropic(
        self,
        messages: List[Dict[str, str]],
        conversation_id: str,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Wraps Anthropic API call with automatic logging.
        Returns the assistant message text + metadata.
        """
        model = model or self.model
        request_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        start = time.time()
        input_text = messages[-1].get("content", "") if messages else ""

        if stream:
            return self._stream_anthropic(
                messages, conversation_id, model, max_tokens,
                request_id, timestamp, start, input_text
            )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={"model": model, "max_tokens": max_tokens, "messages": messages},
                    timeout=60
                )
                resp.raise_for_status()
                data = resp.json()

            latency_ms = (time.time() - start) * 1000
            output_text = data["content"][0]["text"]
            usage = data.get("usage", {})

            metadata = InferenceMetadata(
                conversation_id=conversation_id,
                provider="anthropic",
                model=model,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                input_preview=input_text[:200],
                output_preview=output_text[:200],
                status="success",
                error_message=None,
                timestamp=timestamp,
                request_id=request_id,
            )

            asyncio.create_task(self.send_log(metadata))

            return {
                "text": output_text,
                "usage": usage,
                "latency_ms": latency_ms,
                "request_id": request_id,
            }

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            metadata = InferenceMetadata(
                conversation_id=conversation_id,
                provider="anthropic",
                model=model,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                input_preview=input_text[:200],
                output_preview="",
                status="error",
                error_message=str(e),
                timestamp=timestamp,
                request_id=request_id,
            )
            asyncio.create_task(self.send_log(metadata))
            raise

    async def _stream_anthropic(
        self, messages, conversation_id, model, max_tokens,
        request_id, timestamp, start, input_text
    ) -> AsyncGenerator[str, None]:
        full_text = ""
        usage = {}
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": model, "max_tokens": max_tokens,
                        "stream": True, "messages": messages
                    },
                    timeout=60
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            import json
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "content_block_delta":
                                    chunk = data.get("delta", {}).get("text", "")
                                    full_text += chunk
                                    yield chunk
                                elif data.get("type") == "message_delta":
                                    usage = data.get("usage", {})
                            except:
                                pass

            latency_ms = (time.time() - start) * 1000
            metadata = InferenceMetadata(
                conversation_id=conversation_id,
                provider="anthropic",
                model=model,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                input_preview=input_text[:200],
                output_preview=full_text[:200],
                status="success",
                error_message=None,
                timestamp=timestamp,
                request_id=request_id,
                streaming=True,
            )
            asyncio.create_task(self.send_log(metadata))

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            metadata = InferenceMetadata(
                conversation_id=conversation_id,
                provider="anthropic",
                model=model,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                input_preview=input_text[:200],
                output_preview="",
                status="error",
                error_message=str(e),
                timestamp=timestamp,
                request_id=request_id,
                streaming=True,
            )
            asyncio.create_task(self.send_log(metadata))
            raise


# Usage example:
# sdk = LLMLoggerSDK(api_key="sk-...", ingestion_url="http://localhost:8000/api/logs/ingest")
# result = await sdk.call_anthropic(messages=[{"role":"user","content":"Hello"}], conversation_id="conv-123")
