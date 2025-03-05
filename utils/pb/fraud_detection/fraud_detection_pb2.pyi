from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

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

class FraudRequest(_message.Message):
    __slots__ = ("user_info", "credit_card")
    USER_INFO_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    user_info: UserInfo
    credit_card: CreditCardInfo
    def __init__(self, user_info: _Optional[_Union[UserInfo, _Mapping]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ...) -> None: ...

class FraudResponse(_message.Message):
    __slots__ = ("approved",)
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    approved: bool
    def __init__(self, approved: bool = ...) -> None: ...
