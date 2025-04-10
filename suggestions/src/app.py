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
import copy
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

SERVICE_NAME = "suggestions"
ORDER_DATA_CACHE = {}

def merge_clocks(local_clock, received_clock):
    """Merges two vector clocks, taking the maximum value for each entry."""
    merged = copy.deepcopy(local_clock)
    for service, time in received_clock.items():
        merged[service] = max(merged.get(service, 0), time)
    return merged

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

    def InitializeSuggestions(self, request, context):
        """
        Handles gRPC requests for initializing suggestions data and caching it.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Suggestions] Initializing suggestions data for order: {request.order_id}")

        order_id = request.order_id

        # Initialize vector clock, potentially merging with incoming clock
        vector_clock = self._initialize_vector_clock()
        if hasattr(request, 'vector_clock') and request.vector_clock:
            incoming_clock = {k: v for k, v in request.vector_clock.clock.items()}
            vector_clock = merge_clocks(vector_clock, incoming_clock)

        # Cache the request data and vector clock
        ORDER_DATA_CACHE[order_id] = {
            "request": request, # Store the InitRequest
            "vector_clock": vector_clock,
            "book_name": request.book_name
        }

        # Increment our clock for this initialization
        ORDER_DATA_CACHE[order_id]["vector_clock"][SERVICE_NAME] += 1
        current_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]

        logger.info(f"[{correlation_id}] [Suggestions] Suggestions data cached for order_id: {order_id}")
        logger.info(f"[{correlation_id}] [Suggestions] Vector clock: {current_clock}")

        # Create response with updated vector clock
        response = suggestions_pb2.EventResponse()
        response.approved = True
        response.message = "Suggestions data initialized successfully"
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time
        # No suggested books at initialization
        return response

    def GetSuggestions(self, request, context):
        """
        Handles gRPC requests for book recommendations (Event f).
        Uses EventRequest and EventResponse.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Suggestions] Getting suggestions (Event f).")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             logger.error(f"[{correlation_id}] [Suggestions] Order ID {order_id} not found in cache.")
             context.set_code(grpc.StatusCode.NOT_FOUND)
             context.set_details(f"Order ID {order_id} not found.")
             response = suggestions_pb2.EventResponse()
             response.approved = False
             response.message = f"Order ID {order_id} not found"
             return response

        # Merge incoming vector clock with our stored clock
        incoming_clock = {k: v for k, v in request.vector_clock.clock.items()}
        ORDER_DATA_CACHE[order_id]["vector_clock"] = merge_clocks(
            ORDER_DATA_CACHE[order_id]["vector_clock"],
            incoming_clock
        )

        # Increment our clock for this operation
        ORDER_DATA_CACHE[order_id]["vector_clock"][SERVICE_NAME] += 1
        current_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]

        logger.info(f"[{correlation_id}] [Suggestions] Vector clock for {order_id}: {current_clock}")

        # Perform the actual suggestion generation
        book_name = ORDER_DATA_CACHE[order_id]["book_name"]
        logger.info(f"[{correlation_id}] [Suggestions] Request received for book: {book_name}")

        response = suggestions_pb2.EventResponse() # Use EventResponse
        is_approved = True
        message = "Suggestions generated successfully."

        try:
            prompt = (
                f"Suggest 3 books similar to '{book_name}'. "
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
                    {"bookId": "123", "title": "The Best Book", "author": "Author"} # Fallback
                ]
                message = "Error parsing AI response, using fallback."

            for suggestion in suggestions_list:
                suggested_book = suggestions_pb2.SuggestedBook(
                    bookId=str(suggestion.get("bookId", "")),
                    title=suggestion.get("title", ""),
                    author=suggestion.get("author", "")
                )
                response.suggested_books.append(suggested_book) # Add to EventResponse

            logger.info(f"[{correlation_id}] [Suggestions] Suggestions generated: {len(response.suggested_books)} items.")

        except Exception as e:
            logger.exception(f"[{correlation_id}] [Suggestions] Exception during suggestion generation: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in suggestions service")
            is_approved = False
            message = f"Internal error: {str(e)}"

        # Populate the EventResponse
        response.approved = is_approved
        response.message = message
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time

        return response

    def ClearSuggestionsCache(self, request, context):
        """
        Handles gRPC requests for clearing cached suggestions data.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Suggestions] Clearing suggestions cache for order: {request.order_id}")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.warning(f"[{correlation_id}] [Suggestions] Order ID {order_id} not found in cache for clearing.")
            response = suggestions_pb2.ClearCacheResponse()
            response.success = True # Consider it a success if it's already gone
            response.message = f"Order ID {order_id} not found in cache"
            return response

        # Check if our vector clock is <= the final vector clock
        final_clock = {k: v for k, v in request.final_vector_clock.clock.items()}
        local_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]

        is_safe_to_clear = True
        for service, time in local_clock.items():
            if time > final_clock.get(service, 0):
                is_safe_to_clear = False
                logger.warning(f"[{correlation_id}] [Suggestions] Vector clock conflict for clearing: local {service}={time} > final {service}={final_clock.get(service, 0)}")
                break

        response = suggestions_pb2.ClearCacheResponse()

        if is_safe_to_clear:
            # Safe to clear the cache
            del ORDER_DATA_CACHE[order_id]
            response.success = True
            response.message = f"Order ID {order_id} cleared from suggestions cache"
            logger.info(f"[{correlation_id}] [Suggestions] Order ID {order_id} cleared from cache")
        else:
            # Vector clock conflict
            response.success = False
            response.message = f"Vector clock conflict for clearing order ID {order_id}"
            logger.warning(f"[{correlation_id}] [Suggestions] Vector clock conflict for clearing order ID {order_id}")

        return response

    def GetSuggestionsLegacy(self, request, context):
        """
        Handles gRPC requests for book recommendations (Legacy Method).
        Uses SuggestionRequest and SuggestionResponse.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Suggestions] Legacy GetSuggestions request received for book: {request.book_name}")

        # This legacy method doesn't interact with the cache or vector clocks directly.
        # It just performs the suggestion logic.

        response = suggestions_pb2.SuggestionResponse()
        try:
            prompt = (
                f"Suggest 3 books similar to '{request.book_name}'. "
                "Return your response as a JSON array of objects, "
                "where each object has keys 'bookId', 'title', and 'author'."
            )
            logger.info(f"[{correlation_id}] [Suggestions] Legacy: Prompt sent to OpenAI.")
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
                logger.error(f"[{correlation_id}] [Suggestions] Legacy: Error parsing OpenAI response: {ai_message}")
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
            logger.info(f"[{correlation_id}] [Suggestions] Legacy: Suggestions generated: {len(response.suggested_books)} items.")
            return response

        except Exception as e:
            logger.exception(f"[{correlation_id}] [Suggestions] Legacy: Exception: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in suggestions service (legacy)")
            response.approved = False # Ensure approved is false on error
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
