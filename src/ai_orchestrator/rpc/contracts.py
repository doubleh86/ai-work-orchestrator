from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, TypeAlias, TypedDict

from ..application import OrchestratorApplication

RPC_VERSION = 1


class RequestScope(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"
    RUN = "run"


@dataclass(frozen=True, slots=True)
class RpcRequest:
    method: str
    params: dict[str, object]
    project_name: str = ""
    run_id: str = ""


RpcHandler = Callable[[OrchestratorApplication, RpcRequest], object]


@dataclass(frozen=True, slots=True)
class RpcRoute:
    scope: RequestScope
    handler: RpcHandler


class RpcErrorPayload(TypedDict):
    code: str
    message: str


class RpcSuccessResponse(TypedDict):
    id: object
    result: object


class RpcFailureResponse(TypedDict):
    id: object
    error: RpcErrorPayload


RpcResponse: TypeAlias = RpcSuccessResponse | RpcFailureResponse
