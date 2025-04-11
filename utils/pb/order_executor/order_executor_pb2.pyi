from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class VoteRequest(_message.Message):
    __slots__ = ("candidate_id", "term", "correlation_id")
    CANDIDATE_ID_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    candidate_id: str
    term: int
    correlation_id: str
    def __init__(self, candidate_id: _Optional[str] = ..., term: _Optional[int] = ..., correlation_id: _Optional[str] = ...) -> None: ...

class VoteResponse(_message.Message):
    __slots__ = ("vote_granted", "term")
    VOTE_GRANTED_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    vote_granted: bool
    term: int
    def __init__(self, vote_granted: bool = ..., term: _Optional[int] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("leader_id", "term", "correlation_id")
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    leader_id: str
    term: int
    correlation_id: str
    def __init__(self, leader_id: _Optional[str] = ..., term: _Optional[int] = ..., correlation_id: _Optional[str] = ...) -> None: ...

class HeartbeatResponse(_message.Message):
    __slots__ = ("success", "term")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    success: bool
    term: int
    def __init__(self, success: bool = ..., term: _Optional[int] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("correlation_id",)
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    correlation_id: str
    def __init__(self, correlation_id: _Optional[str] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("executor_id", "state", "current_term", "processed_orders", "leader_id")
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TERM_FIELD_NUMBER: _ClassVar[int]
    PROCESSED_ORDERS_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    state: str
    current_term: int
    processed_orders: int
    leader_id: str
    def __init__(self, executor_id: _Optional[str] = ..., state: _Optional[str] = ..., current_term: _Optional[int] = ..., processed_orders: _Optional[int] = ..., leader_id: _Optional[str] = ...) -> None: ...
