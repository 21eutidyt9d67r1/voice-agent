from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol


DEFAULT_KEY_PREFIX = "voice-agent:noauth"
DEFAULT_TTL_SECONDS = 172800


class StateStore(Protocol):
    def get(self, kind: str, key: str) -> dict[str, Any] | None: ...

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None: ...

    def put_if_absent(self, kind: str, key: str, document: dict[str, Any]) -> bool: ...

    def keys(self, kind: str) -> list[str]: ...

    def next_number(self, kind: str, floor: int) -> int: ...


class MemoryStateStore:
    """Process-local state for tests and single-process local runs."""

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        raw = self._documents.get((kind, key))
        return json.loads(raw) if raw is not None else None

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None:
        with self._lock:
            self._documents[(kind, key)] = json.dumps(document)

    def put_if_absent(self, kind: str, key: str, document: dict[str, Any]) -> bool:
        with self._lock:
            if (kind, key) in self._documents:
                return False
            self._documents[(kind, key)] = json.dumps(document)
            return True

    def keys(self, kind: str) -> list[str]:
        return sorted(key for stored_kind, key in self._documents if stored_kind == kind)

    def next_number(self, kind: str, floor: int) -> int:
        with self._lock:
            value = max(self._counters.get(kind, floor), floor) + 1
            self._counters[kind] = value
            return value


class RedisStateStore:
    """Shared state across replicas; every key lives under its own prefix and expires."""

    def __init__(self, client: Any, *, key_prefix: str, ttl_seconds: int) -> None:
        if ttl_seconds < 60:
            raise ValueError("mock-tool-call state TTL must be at least 60 seconds")
        self._client = client
        self._prefix = f"{key_prefix.strip().rstrip(':')}:mock-tool-call"
        self._ttl = ttl_seconds

    def _key(self, kind: str, key: str) -> str:
        return f"{self._prefix}:{kind}:{key}"

    def _index(self, kind: str) -> str:
        return f"{self._prefix}:{kind}:index"

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        raw = self._client.get(self._key(kind, key))
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None:
        self._client.set(self._key(kind, key), json.dumps(document), ex=self._ttl)
        self._client.sadd(self._index(kind), key)
        self._client.expire(self._index(kind), self._ttl)

    def put_if_absent(self, kind: str, key: str, document: dict[str, Any]) -> bool:
        created = bool(
            self._client.set(self._key(kind, key), json.dumps(document), ex=self._ttl, nx=True)
        )
        if created:
            self._client.sadd(self._index(kind), key)
            self._client.expire(self._index(kind), self._ttl)
        return created

    def keys(self, kind: str) -> list[str]:
        members = self._client.smembers(self._index(kind))
        return sorted(
            member.decode("utf-8") if isinstance(member, bytes) else str(member)
            for member in members
        )

    def next_number(self, kind: str, floor: int) -> int:
        counter = f"{self._prefix}:{kind}:counter"
        self._client.set(counter, floor, nx=True)
        value = int(self._client.incr(counter))
        self._client.expire(counter, self._ttl)
        return value


@dataclass(frozen=True)
class StoreConfig:
    redis_url: str
    redis_password: str | None
    key_prefix: str
    ttl_seconds: int
    require_shared: bool

    @classmethod
    def from_environment(cls, environment: dict[str, str] | None = None) -> "StoreConfig":
        values = os.environ if environment is None else environment
        redis_url = (
            values.get("MOCK_TOOL_CALL_REDIS_URL", "").strip()
            or values.get("NOAUTH_MCP_REDIS_URL", "").strip()
        )
        password = (
            values.get("MOCK_TOOL_CALL_REDIS_PASSWORD", "").strip()
            or values.get("NOAUTH_MCP_REDIS_PASSWORD", "").strip()
        )
        try:
            ttl = int(values.get("NOAUTH_MCP_STATE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
        except ValueError as error:
            raise ValueError("NOAUTH_MCP_STATE_TTL_SECONDS must be an integer") from error
        return cls(
            redis_url=redis_url,
            redis_password=password or None,
            key_prefix=values.get("NOAUTH_MCP_REDIS_KEY_PREFIX", DEFAULT_KEY_PREFIX).strip()
            or DEFAULT_KEY_PREFIX,
            ttl_seconds=ttl,
            require_shared=values.get("NOAUTH_MCP_REQUIRE_SHARED_STATE", "").lower() == "true",
        )


class LazyRedisStateStore:
    """Connects on the first tool call, so registering the pack never touches the network."""

    def __init__(self, config: StoreConfig) -> None:
        self._config = config
        self._store: RedisStateStore | None = None
        self._lock = threading.Lock()

    def _resolve(self) -> RedisStateStore:
        if self._store is None:
            with self._lock:
                if self._store is None:
                    from redis import Redis

                    options: dict[str, Any] = {
                        "decode_responses": True,
                        "socket_connect_timeout": 5,
                        "socket_timeout": 5,
                        "health_check_interval": 30,
                    }
                    if self._config.redis_password is not None:
                        options["pass" + "word"] = self._config.redis_password
                    self._store = RedisStateStore(
                        Redis.from_url(self._config.redis_url, **options),
                        key_prefix=self._config.key_prefix,
                        ttl_seconds=self._config.ttl_seconds,
                    )
        return self._store

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return self._resolve().get(kind, key)

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None:
        self._resolve().put(kind, key, document)

    def put_if_absent(self, kind: str, key: str, document: dict[str, Any]) -> bool:
        return self._resolve().put_if_absent(kind, key, document)

    def keys(self, kind: str) -> list[str]:
        return self._resolve().keys(kind)

    def next_number(self, kind: str, floor: int) -> int:
        return self._resolve().next_number(kind, floor)


def store_from_environment(environment: dict[str, str] | None = None) -> StateStore:
    config = StoreConfig.from_environment(environment)
    if config.redis_url:
        if config.ttl_seconds < 60:
            raise ValueError("NOAUTH_MCP_STATE_TTL_SECONDS must be at least 60")
        return LazyRedisStateStore(config)
    if config.require_shared:
        raise ValueError("NOAUTH_MCP_REDIS_URL is required for shared mock-tool-call state")
    return MemoryStateStore()
