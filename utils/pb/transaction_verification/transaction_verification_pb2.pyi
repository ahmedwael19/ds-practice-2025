from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

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

class InitRequest(_message.Message):
    __slots__ = ("order_id", "items", "credit_card", "billingAddress", "termsAndConditionsAccepted", "user_contact", "user_name", "vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    BILLINGADDRESS_FIELD_NUMBER: _ClassVar[int]
    TERMSANDCONDITIONSACCEPTED_FIELD_NUMBER: _ClassVar[int]
    USER_CONTACT_FIELD_NUMBER: _ClassVar[int]
    USER_NAME_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    items: _containers.RepeatedCompositeFieldContainer[Item]
    credit_card: CreditCardInfo
    billingAddress: Address
    termsAndConditionsAccepted: bool
    user_contact: str
    user_name: str
    vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ..., billingAddress: _Optional[_Union[Address, _Mapping]] = ..., termsAndConditionsAccepted: bool = ..., user_contact: _Optional[str] = ..., user_name: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

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

class TransactionRequest(_message.Message):
    __slots__ = ("order_id", "items", "credit_card", "shippingMethod", "discountCode", "billingAddress", "termsAndConditionsAccepted")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    SHIPPINGMETHOD_FIELD_NUMBER: _ClassVar[int]
    DISCOUNTCODE_FIELD_NUMBER: _ClassVar[int]
    BILLINGADDRESS_FIELD_NUMBER: _ClassVar[int]
    TERMSANDCONDITIONSACCEPTED_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    items: _containers.RepeatedCompositeFieldContainer[Item]
    credit_card: CreditCardInfo
    shippingMethod: str
    discountCode: str
    billingAddress: Address
    termsAndConditionsAccepted: bool
    def __init__(self, order_id: _Optional[str] = ..., items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ..., shippingMethod: _Optional[str] = ..., discountCode: _Optional[str] = ..., billingAddress: _Optional[_Union[Address, _Mapping]] = ..., termsAndConditionsAccepted: bool = ...) -> None: ...

class TransactionResponse(_message.Message):
    __slots__ = ("approved", "message")
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    approved: bool
    message: str
    def __init__(self, approved: bool = ..., message: _Optional[str] = ...) -> None: ...
