from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SuggestedBook(_message.Message):
    __slots__ = ("bookId", "title", "author")
    BOOKID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    bookId: str
    title: str
    author: str
    def __init__(self, bookId: _Optional[str] = ..., title: _Optional[str] = ..., author: _Optional[str] = ...) -> None: ...

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
