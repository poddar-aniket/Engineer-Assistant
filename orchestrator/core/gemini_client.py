import json
import logging
import time
from collections import deque
from typing import Any

from google import genai
from google.genai import types

from config.settings import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket style rate limiter — enforces max N calls per 60 seconds."""

    def __init__(self, rpm: int) -> None:
        self._rpm = rpm
        self._timestamps: deque[float] = deque()

    def wait_if_needed(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > 60.0:
            self._timestamps.popleft()

        if len(self._timestamps) >= self._rpm:
            oldest = self._timestamps[0]
            sleep_for = 60.0 - (now - oldest) + 0.1
            if sleep_for > 0:
                logger.debug("Rate limit reached — sleeping %.1f s", sleep_for)
                time.sleep(sleep_for)

        self._timestamps.append(time.monotonic())


class GeminiClient:
    """
    Thin wrapper around google-genai 2.x SDK.

    Responsibilities:
    - Initialise the client once and reuse it.
    - Enforce 12 RPM rate limit on every call.
    - Retry up to 3 times on transient errors (429, 503, etc.).
    - Expose:
        generate(prompt)              -> str
        function_call(prompt, tools)  -> dict  {"name": ..., "args": {...}}
        batch_generate(prompts)       -> list[str]
    """

    _MAX_RETRIES = 3
    _RETRY_BACKOFF = [2, 5, 10]

    def __init__(self) -> None:
        self._client: genai.Client | None = None
        self._rate_limiter = RateLimiter(rpm=settings.GEMINI_RPM_LIMIT)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info("GeminiClient initialised with model=%s", settings.GEMINI_MODEL)

    def _require_init(self) -> None:
        if self._client is None:
            raise RuntimeError("GeminiClient.initialize() must be called first")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Send a plain text prompt, return the text of the response."""
        self._require_init()
        response = self._call_with_retry(prompt)
        return response.text or ""

    def function_call(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Send a prompt with a tool schema, return the parsed function call.

        Returns:
            {"name": str, "args": dict}

        Raises ValueError if Gemini does not return a function call.
        """
        self._require_init()
        genai_tools = self._build_genai_tools(tools)
        response = self._call_with_retry(prompt, genai_tools=genai_tools)
        return self._extract_function_call(response)

    def batch_generate(self, prompts: list[str]) -> list[str]:
        """
        Run multiple prompts sequentially, respecting rate limits.
        Returns results in the same order as the input list.
        """
        return [self.generate(p) for p in prompts]

    # ------------------------------------------------------------------
    # Internal — HTTP call + retry
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        prompt: str,
        genai_tools: list[types.Tool] | None = None,
    ) -> Any:
        last_error: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                self._rate_limiter.wait_if_needed()

                config = None
                if genai_tools:
                    config = types.GenerateContentConfig(tools=genai_tools)

                response = self._client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
                return response

            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                is_transient = any(
                    kw in err_str
                    for kw in ("429", "503", "quota", "rate", "timeout", "unavailable")
                )
                if not is_transient or attempt == self._MAX_RETRIES - 1:
                    raise

                wait = self._RETRY_BACKOFF[attempt]
                logger.warning(
                    "Gemini transient error (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1,
                    self._MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise last_error

    # ------------------------------------------------------------------
    # Internal — response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_function_call(response: Any) -> dict[str, Any]:
        """Pull the function call out of a Gemini response."""
        try:
            for part in response.candidates[0].content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    return {
                        "name": fc.name,
                        "args": dict(fc.args),
                    }
        except (AttributeError, IndexError, KeyError):
            pass

        # Fallback: try response text as JSON
        try:
            text = response.text.strip()
            if text.startswith("{"):
                return json.loads(text)
        except Exception:
            pass

        raise ValueError(
            "Gemini did not return a function call. "
            f"Raw response: {getattr(response, 'text', repr(response))}"
        )

    # ------------------------------------------------------------------
    # Internal — tool schema builder
    # ------------------------------------------------------------------

    def _build_genai_tools(self, tools: list[dict[str, Any]]) -> list[types.Tool]:
        """
        Convert our tool schema dicts into google-genai types.Tool objects.
        """
        function_declarations = []

        for tool in tools:
            properties = {}
            for param_name, param_def in tool.get("parameters", {}).items():
                properties[param_name] = types.Schema(
                    type=self._type_string(param_def.get("type", "string")),
                    description=param_def.get("description", ""),
                )

            schema = types.Schema(
                type="OBJECT",
                properties=properties,
                required=tool.get("required", []),
            ) if properties else None

            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=schema,
                )
            )

        return [types.Tool(function_declarations=function_declarations)]

    @staticmethod
    def _type_string(python_type: str) -> str:
        """Map JSON schema type names to Gemini type strings."""
        mapping = {
            "string":  "STRING",
            "integer": "INTEGER",
            "number":  "NUMBER",
            "boolean": "BOOLEAN",
            "array":   "ARRAY",
            "object":  "OBJECT",
        }
        return mapping.get(python_type.lower(), "STRING")