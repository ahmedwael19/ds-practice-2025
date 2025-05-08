from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DBVoteStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DB_VOTE_UNSPECIFIED: _ClassVar[DBVoteStatus]
    DB_VOTE_COMMIT: _ClassVar[DBVoteStatus]
    DB_VOTE_ABORT: _ClassVar[DBVoteStatus]

class DBAckStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DB_ACK_UNSPECIFIED: _ClassVar[DBAckStatus]
    DB_ACK_SUCCESS: _ClassVar[DBAckStatus]
    DB_ACK_FAILURE: _ClassVar[DBAckStatus]
DB_VOTE_UNSPECIFIED: DBVoteStatus
DB_VOTE_COMMIT: DBVoteStatus
DB_VOTE_ABORT: DBVoteStatus
DB_ACK_UNSPECIFIED: DBAckStatus
DB_ACK_SUCCESS: DBAckStatus
DB_ACK_FAILURE: DBAckStatus

class BookOperation(_message.Message):
    __slots__ = ("book_id", "quantity_change")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_CHANGE_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    quantity_change: int
    def __init__(self, book_id: _Optional[str] = ..., quantity_change: _Optional[int] = ...) -> None: ...

class DBPrepareRequest(_message.Message):
    __slots__ = ("transaction_id", "operations")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    operations: _containers.RepeatedCompositeFieldContainer[BookOperation]
    def __init__(self, transaction_id: _Optional[str] = ..., operations: _Optional[_Iterable[_Union[BookOperation, _Mapping]]] = ...) -> None: ...

class DBVoteTransactionResponse(_message.Message):
    __slots__ = ("transaction_id", "vote", "message")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    VOTE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    vote: DBVoteStatus
    message: str
    def __init__(self, transaction_id: _Optional[str] = ..., vote: _Optional[_Union[DBVoteStatus, str]] = ..., message: _Optional[str] = ...) -> None: ...

class DBTransactionRequest(_message.Message):
    __slots__ = ("transaction_id",)
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    def __init__(self, transaction_id: _Optional[str] = ...) -> None: ...

class DBAckTransactionResponse(_message.Message):
    __slots__ = ("transaction_id", "status", "message")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    status: DBAckStatus
    message: str
    def __init__(self, transaction_id: _Optional[str] = ..., status: _Optional[_Union[DBAckStatus, str]] = ..., message: _Optional[str] = ...) -> None: ...

class BookStock(_message.Message):
    __slots__ = ("book_id", "quantity")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    quantity: int
    def __init__(self, book_id: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...

class ReadStockRequest(_message.Message):
    __slots__ = ("book_id",)
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    def __init__(self, book_id: _Optional[str] = ...) -> None: ...

class ReadStockResponse(_message.Message):
    __slots__ = ("book_id", "quantity", "success", "message")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    quantity: int
    success: bool
    message: str
    def __init__(self, book_id: _Optional[str] = ..., quantity: _Optional[int] = ..., success: bool = ..., message: _Optional[str] = ...) -> None: ...

class WriteStockRequest(_message.Message):
    __slots__ = ("book_id", "quantity")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    quantity: int
    def __init__(self, book_id: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...

class WriteStockResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class DecrementStockRequest(_message.Message):
    __slots__ = ("book_id", "amount_to_decrement")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_TO_DECREMENT_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    amount_to_decrement: int
    def __init__(self, book_id: _Optional[str] = ..., amount_to_decrement: _Optional[int] = ...) -> None: ...

class DecrementStockResponse(_message.Message):
    __slots__ = ("book_id", "new_quantity", "success", "message")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_QUANTITY_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    new_quantity: int
    success: bool
    message: str
    def __init__(self, book_id: _Optional[str] = ..., new_quantity: _Optional[int] = ..., success: bool = ..., message: _Optional[str] = ...) -> None: ...

class DBVoteRequest(_message.Message):
    __slots__ = ("term", "candidate_id")
    TERM_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_ID_FIELD_NUMBER: _ClassVar[int]
    term: int
    candidate_id: str
    def __init__(self, term: _Optional[int] = ..., candidate_id: _Optional[str] = ...) -> None: ...

class DBVoteResponse(_message.Message):
    __slots__ = ("term", "vote_granted")
    TERM_FIELD_NUMBER: _ClassVar[int]
    VOTE_GRANTED_FIELD_NUMBER: _ClassVar[int]
    term: int
    vote_granted: bool
    def __init__(self, term: _Optional[int] = ..., vote_granted: bool = ...) -> None: ...

class DBLogEntry(_message.Message):
    __slots__ = ("operation", "book_id", "value")
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    operation: str
    book_id: str
    value: int
    def __init__(self, operation: _Optional[str] = ..., book_id: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...

class DBAppendEntriesRequest(_message.Message):
    __slots__ = ("term", "leader_id")
    TERM_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    term: int
    leader_id: str
    def __init__(self, term: _Optional[int] = ..., leader_id: _Optional[str] = ...) -> None: ...

class DBAppendEntriesResponse(_message.Message):
    __slots__ = ("term", "success")
    TERM_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    term: int
    success: bool
    def __init__(self, term: _Optional[int] = ..., success: bool = ...) -> None: ...

class InternalReplicateRequest(_message.Message):
    __slots__ = ("book_id", "new_quantity", "operation_id")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_QUANTITY_FIELD_NUMBER: _ClassVar[int]
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    new_quantity: int
    operation_id: str
    def __init__(self, book_id: _Optional[str] = ..., new_quantity: _Optional[int] = ..., operation_id: _Optional[str] = ...) -> None: ...

class InternalReplicateResponse(_message.Message):
    __slots__ = ("success", "node_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    node_id: str
    def __init__(self, success: bool = ..., node_id: _Optional[str] = ...) -> None: ...

class GetNodeRoleRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetNodeRoleResponse(_message.Message):
    __slots__ = ("node_id", "role", "term", "leader_id")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    role: str
    term: int
    leader_id: str
    def __init__(self, node_id: _Optional[str] = ..., role: _Optional[str] = ..., term: _Optional[int] = ..., leader_id: _Optional[str] = ...) -> None: ...
