from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Item(_message.Message):
    __slots__ = ("name", "quantity")
    NAME_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    name: str
    quantity: int
    def __init__(self, name: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...

class CreditCardInfo(_message.Message):
    __slots__ = ("number", "expirationDate", "cvv")
    NUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRATIONDATE_FIELD_NUMBER: _ClassVar[int]
    CVV_FIELD_NUMBER: _ClassVar[int]
    number: str
    expirationDate: str
    cvv: str
    def __init__(self, number: _Optional[str] = ..., expirationDate: _Optional[str] = ..., cvv: _Optional[str] = ...) -> None: ...

class Address(_message.Message):
    __slots__ = ("street", "city", "state", "zip", "country")
    STREET_FIELD_NUMBER: _ClassVar[int]
    CITY_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ZIP_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_FIELD_NUMBER: _ClassVar[int]
    street: str
    city: str
    state: str
    zip: str
    country: str
    def __init__(self, street: _Optional[str] = ..., city: _Optional[str] = ..., state: _Optional[str] = ..., zip: _Optional[str] = ..., country: _Optional[str] = ...) -> None: ...

class OrderData(_message.Message):
    __slots__ = ("items", "user_name", "user_contact", "credit_card", "billing_address", "shipping_method", "gift_wrapping", "terms_and_conditions_accepted", "user_comment")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    USER_NAME_FIELD_NUMBER: _ClassVar[int]
    USER_CONTACT_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    BILLING_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    SHIPPING_METHOD_FIELD_NUMBER: _ClassVar[int]
    GIFT_WRAPPING_FIELD_NUMBER: _ClassVar[int]
    TERMS_AND_CONDITIONS_ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    USER_COMMENT_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Item]
    user_name: str
    user_contact: str
    credit_card: CreditCardInfo
    billing_address: Address
    shipping_method: str
    gift_wrapping: bool
    terms_and_conditions_accepted: bool
    user_comment: str
    def __init__(self, items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ..., user_name: _Optional[str] = ..., user_contact: _Optional[str] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ..., billing_address: _Optional[_Union[Address, _Mapping]] = ..., shipping_method: _Optional[str] = ..., gift_wrapping: bool = ..., terms_and_conditions_accepted: bool = ..., user_comment: _Optional[str] = ...) -> None: ...

class EnqueueRequest(_message.Message):
    __slots__ = ("order_id", "order_data", "vector_clock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_DATA_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    order_data: OrderData
    vector_clock: _containers.ScalarMap[str, int]
    def __init__(self, order_id: _Optional[str] = ..., order_data: _Optional[_Union[OrderData, _Mapping]] = ..., vector_clock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class EnqueueResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class DequeueRequest(_message.Message):
    __slots__ = ("executor_id",)
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    def __init__(self, executor_id: _Optional[str] = ...) -> None: ...

class DequeueResponse(_message.Message):
    __slots__ = ("success", "message", "order_id", "order_data", "vector_clock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_DATA_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    order_id: str
    order_data: OrderData
    vector_clock: _containers.ScalarMap[str, int]
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., order_id: _Optional[str] = ..., order_data: _Optional[_Union[OrderData, _Mapping]] = ..., vector_clock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class QueueStatusRequest(_message.Message):
    __slots__ = ("executor_id",)
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    def __init__(self, executor_id: _Optional[str] = ...) -> None: ...

class QueueStatusResponse(_message.Message):
    __slots__ = ("has_pending_orders", "queue_size")
    HAS_PENDING_ORDERS_FIELD_NUMBER: _ClassVar[int]
    QUEUE_SIZE_FIELD_NUMBER: _ClassVar[int]
    has_pending_orders: bool
    queue_size: int
    def __init__(self, has_pending_orders: bool = ..., queue_size: _Optional[int] = ...) -> None: ...
