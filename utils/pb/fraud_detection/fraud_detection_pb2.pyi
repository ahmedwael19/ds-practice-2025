from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VectorClock(_message.Message):
    __slots__ = ("clock",)
    class ClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    CLOCK_FIELD_NUMBER: _ClassVar[int]
    clock: _containers.ScalarMap[str, int]
    def __init__(self, clock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class EventRequest(_message.Message):
    __slots__ = ("order_id", "vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class EventResponse(_message.Message):
    __slots__ = ("approved", "message", "vector_clock")
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    approved: bool
    message: str
    vector_clock: VectorClock
    def __init__(self, approved: bool = ..., message: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class UserInfo(_message.Message):
    __slots__ = ("name", "contact")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTACT_FIELD_NUMBER: _ClassVar[int]
    name: str
    contact: str
    def __init__(self, name: _Optional[str] = ..., contact: _Optional[str] = ...) -> None: ...

class CreditCardInfo(_message.Message):
    __slots__ = ("number", "expirationDate", "cvv")
    NUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRATIONDATE_FIELD_NUMBER: _ClassVar[int]
    CVV_FIELD_NUMBER: _ClassVar[int]
    number: str
    expirationDate: str
    cvv: str
    def __init__(self, number: _Optional[str] = ..., expirationDate: _Optional[str] = ..., cvv: _Optional[str] = ...) -> None: ...

class InitRequest(_message.Message):
    __slots__ = ("order_id", "user_info", "credit_card", "vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    USER_INFO_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    user_info: UserInfo
    credit_card: CreditCardInfo
    vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., user_info: _Optional[_Union[UserInfo, _Mapping]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class ClearCacheRequest(_message.Message):
    __slots__ = ("order_id", "final_vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    FINAL_VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    final_vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., final_vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class ClearCacheResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class FraudRequest(_message.Message):
    __slots__ = ("user_info", "credit_card", "transaction_id", "timestamp", "order_id")
    USER_INFO_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    user_info: UserInfo
    credit_card: CreditCardInfo
    transaction_id: str
    timestamp: str
    order_id: str
    def __init__(self, user_info: _Optional[_Union[UserInfo, _Mapping]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ..., transaction_id: _Optional[str] = ..., timestamp: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class FraudResponse(_message.Message):
    __slots__ = ("approved", "confidence", "reason", "message")
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    approved: bool
    confidence: float
    reason: str
    message: str
    def __init__(self, approved: bool = ..., confidence: _Optional[float] = ..., reason: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...
