"""
Suggestions Service for Book Recommendations

This module implements a gRPC service that provides book suggestions based on user input.
It integrates with OpenAI's GPT model to generate book recommendations.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-03-07
"""

import os
import sys
import json
import logging
import grpc
import openai
from concurrent import futures
from random import randrange

# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2
import suggestions_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("suggestions")

ORDER_DATA_CACHE = {}

# Initialize OpenAI API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

class SuggestionsService(suggestions_pb2_grpc.SuggestionsServiceServicer):
    """
    gRPC Service that provides book suggestions based on user input.
    """

    def _initialize_vector_clock(self):
        """
        Initialize vector clock for the service
        """
        return {
            "transaction_verification": 0,
            "fraud_detection": 0,
            "suggestions": 0
        }

    def GetSuggestions(self, request, context):
        """
        Handles gRPC requests for book recommendations.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            ORDER_DATA_CACHE[order_id] = {
                "request": request,
                "vector_clock": self._initialize_vector_clock()
            }
            logger.info(f"[{correlation_id}] [Suggestions] Order data cached for order_id: {order_id}")

        logger.info(f"[{correlation_id}] [Suggestions] Request received for book: {request.book_name}")

        response = suggestions_pb2.SuggestionResponse()
        try:
            prompt = (
                f"Suggest 3 books similar to '{request.book_name}'. "
                "Return your response as a JSON array of objects, "
                "where each object has keys 'bookId', 'title', and 'author'."
            )
            logger.info(f"[{correlation_id}] [Suggestions] Prompt sent to OpenAI.")
            ai_response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a book recommendation AI."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            ai_message = ai_response.choices[0].message.content.strip()

            # Remove markdown formatting if present
            if ai_message.startswith("```json"):
                ai_message = ai_message[len("```json"):].strip()
            if ai_message.endswith("```"):
                ai_message = ai_message[:-3].strip()

            try:
                suggestions_list = json.loads(ai_message)
            except json.JSONDecodeError:
                logger.error(f"[{correlation_id}] [Suggestions] Error parsing OpenAI response: {ai_message}")
                suggestions_list = [
                    {"bookId": "123", "title": "The Best Book", "author": "Author"}
                ]

            for suggestion in suggestions_list:
                suggested_book = suggestions_pb2.SuggestedBook(
                    bookId=str(suggestion.get("bookId", "")),
                    title=suggestion.get("title", ""),
                    author=suggestion.get("author", "")
                )
                response.suggested_books.append(suggested_book)

            response.approved = True
            logger.info(f"[{correlation_id}] [Suggestions] Suggestions generated: {len(response.suggested_books)} items.")
            return response

        except Exception as e:
            logger.exception(f"[{correlation_id}] [Suggestions] Exception: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in suggestions service")
            return response

def serve():
    """
    Starts the gRPC server and listens for incoming requests.
    """
    server = grpc.server(futures.ThreadPoolExecutor())
    suggestions_pb2_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsService(), server)
    port = "50053"
    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"Suggestions Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
