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
    __slots__ = ("order_id", "vector_clock", "book_name")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    BOOK_NAME_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    vector_clock: VectorClock
    book_name: str
    def __init__(self, order_id: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ..., book_name: _Optional[str] = ...) -> None: ...

class EventResponse(_message.Message):
    __slots__ = ("approved", "message", "vector_clock", "suggested_books")
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_BOOKS_FIELD_NUMBER: _ClassVar[int]
    approved: bool
    message: str
    vector_clock: VectorClock
    suggested_books: _containers.RepeatedCompositeFieldContainer[SuggestedBook]
    def __init__(self, approved: bool = ..., message: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ..., suggested_books: _Optional[_Iterable[_Union[SuggestedBook, _Mapping]]] = ...) -> None: ...

class SuggestedBook(_message.Message):
    __slots__ = ("bookId", "title", "author")
    BOOKID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    bookId: str
    title: str
    author: str
    def __init__(self, bookId: _Optional[str] = ..., title: _Optional[str] = ..., author: _Optional[str] = ...) -> None: ...

class InitRequest(_message.Message):
    __slots__ = ("order_id", "book_name", "vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    BOOK_NAME_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    book_name: str
    vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., book_name: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

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

class SuggestionRequest(_message.Message):
    __slots__ = ("book_name", "order_id")
    BOOK_NAME_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    book_name: str
    order_id: str
    def __init__(self, book_name: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class SuggestionResponse(_message.Message):
    __slots__ = ("suggested_books", "approved")
    SUGGESTED_BOOKS_FIELD_NUMBER: _ClassVar[int]
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    suggested_books: _containers.RepeatedCompositeFieldContainer[SuggestedBook]
    approved: bool
    def __init__(self, suggested_books: _Optional[_Iterable[_Union[SuggestedBook, _Mapping]]] = ..., approved: bool = ...) -> None: ...
