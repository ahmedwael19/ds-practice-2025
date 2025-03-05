import sys
import os
from random import randrange

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2 as suggestions
import suggestions_pb2_grpc as suggestions_grpc

import grpc
from concurrent import futures

# Create a class to define the server functions, derived from
class SuggestionsService(suggestions_grpc.SuggestionsServiceServicer):
    def GetSuggestions(self, request, context):
        response = suggestions.SuggestionResponse()
        # Use name to suggest book with AI
        book_name = request.book_name

        suggested_books = [{'bookId': '123', 'title': 'The Best Book', 'author': 'Author'},
                           {'bookId': '124', 'title': 'Harry Potter', 'author': 'JK Rowling'},
                           {'bookId': '125', 'title': 'Lord of the Rings', 'author': 'Author 1'},
                           {'bookId': '126', 'title': 'Dune', 'author': 'Author 2'},
                           {'bookId': '127', 'title': 'Sherlock Holmes', 'author': 'Author 3'},
                           {'bookId': '128', 'title': 'Hello World', 'author': 'Author 4'},
                           {'bookId': '129', 'title': 'I dislike distributed systems', 'author': 'Author 5'}]
        
        indices = [randrange(7) for i in range(3)]
        for indice in indices:
            sb = suggestions.SuggestedBook()
            sb.bookId = suggested_books[indice]['bookId']
            sb.title = suggested_books[indice]['title']
            sb.author = suggested_books[indice]['author']
            response.suggested_books.append(sb)

        # Always True by default
        response.approved = True
        # Return the response object
        return response

def serve():
    # Create a gRPC server
    server = grpc.server(futures.ThreadPoolExecutor())
    suggestions_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsService(), server)
    # Listen on port 50053
    port = "50053"
    server.add_insecure_port("[::]:" + port)
    # Start the server
    server.start()
    print("Server started. Listening on port 50053.")
    # Keep thread alive
    server.wait_for_termination()

if __name__ == '__main__':
    serve()