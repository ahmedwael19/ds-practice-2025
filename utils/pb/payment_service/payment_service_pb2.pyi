from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Vote(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    VOTE_UNSPECIFIED: _ClassVar[Vote]
    VOTE_COMMIT: _ClassVar[Vote]
    VOTE_ABORT: _ClassVar[Vote]

class AckStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACK_UNSPECIFIED: _ClassVar[AckStatus]
    ACK_SUCCESS: _ClassVar[AckStatus]
    ACK_FAILURE: _ClassVar[AckStatus]
VOTE_UNSPECIFIED: Vote
VOTE_COMMIT: Vote
VOTE_ABORT: Vote
ACK_UNSPECIFIED: AckStatus
ACK_SUCCESS: AckStatus
ACK_FAILURE: AckStatus

class PaymentPrepareRequest(_message.Message):
    __slots__ = ("transaction_id", "order_id", "amount")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    order_id: str
    amount: float
    def __init__(self, transaction_id: _Optional[str] = ..., order_id: _Optional[str] = ..., amount: _Optional[float] = ...) -> None: ...

class VoteResponse(_message.Message):
    __slots__ = ("transaction_id", "vote", "message")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    VOTE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    vote: Vote
    message: str
    def __init__(self, transaction_id: _Optional[str] = ..., vote: _Optional[_Union[Vote, str]] = ..., message: _Optional[str] = ...) -> None: ...

class TransactionRequest(_message.Message):
    __slots__ = ("transaction_id",)
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    def __init__(self, transaction_id: _Optional[str] = ...) -> None: ...

class AckResponse(_message.Message):
    __slots__ = ("transaction_id", "status", "message")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    status: AckStatus
    message: str
    def __init__(self, transaction_id: _Optional[str] = ..., status: _Optional[_Union[AckStatus, str]] = ..., message: _Optional[str] = ...) -> None: ...
