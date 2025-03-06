import sys
import os
import grpc
import logging
from concurrent import futures
from random import randrange

FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2, suggestions_pb2_grpc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("suggestions")

class SuggestionsService(suggestions_pb2_grpc.SuggestionsServiceServicer):
    def GetSuggestions(self, request, context):
        cid = "N/A"
        for key, value in context.invocation_metadata():
            if key == "correlation-id":
                cid = value
                break
        logger.info(f"[{cid}] Received GetSuggestions request for book_name: {request.book_name}")
        response = suggestions_pb2.SuggestionResponse()
        suggested_books_list = [
            {'bookId': '123', 'title': 'The Best Book', 'author': 'Author'},
            {'bookId': '124', 'title': 'Harry Potter', 'author': 'JK Rowling'},
            {'bookId': '125', 'title': 'Lord of the Rings', 'author': 'Author 1'},
            {'bookId': '126', 'title': 'Dune', 'author': 'Author 2'},
            {'bookId': '127', 'title': 'Sherlock Holmes', 'author': 'Author 3'},
            {'bookId': '128', 'title': 'Hello World', 'author': 'Author 4'},
            {'bookId': '129', 'title': 'I dislike distributed systems', 'author': 'Author 5'}
        ]
        indices = [randrange(7) for _ in range(3)]
        for i in indices:
            sb = suggestions_pb2.SuggestedBook()
            sb.bookId = suggested_books_list[i]['bookId']
            sb.title = suggested_books_list[i]['title']
            sb.author = suggested_books_list[i]['author']
            response.suggested_books.append(sb)
        response.approved = True
        logger.info(f"[{cid}] GetSuggestions completed with {len(response.suggested_books)} suggestions")
        return response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor())
    suggestions_pb2_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsService(), server)
    port = "50053"
    server.add_insecure_port("[::]:" + port)
    logger.info(f"Suggestions Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()