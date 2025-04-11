"""
Fraud Detection Service

This module implements a gRPC service that evaluates transactions for potential fraud.
It integrates with OpenAI's GPT model and uses additional rules to determine whether a transaction is fraudulent.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-04-10
"""

import os
import sys
import json
import logging
import grpc
import openai
import time
import re
import hashlib
import copy
from concurrent import futures
from datetime import datetime

# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("fraud_detection")

# Initialize OpenAI API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    # log warning
    logger.warning("OpenAI API key not set. Please set the OPENAI_API_KEY environment variable.")
# Cache for tracking repeated fraud attempts (simple in-memory implementation)
FRAUD_ATTEMPT_CACHE = {}
# Maximum number of attempts within timeframe
MAX_ATTEMPTS_THRESHOLD = 5
# Timeframe in seconds (1 hour)
ATTEMPT_TIMEFRAME = 3600

ORDER_DATA_CACHE = {}

SERVICE_NAME = "fraud_detection"

def merge_clocks(local_clock, received_clock):
    """
    Merges two vector clocks by taking the maximum value for each service entry.
    Ensures proper causality tracking in the distributed system.
    
    Args:
        local_clock: Dictionary with current local vector clock
        received_clock: Dictionary with received vector clock
        
    Returns:
        Dictionary with merged vector clock
    """
    merged = copy.deepcopy(local_clock)
    for service, time in received_clock.items():
        merged[service] = max(merged.get(service, 0), time)
    return merged


class FraudService(fraud_detection_grpc.FraudServiceServicer):
    """
    gRPC Service that evaluates transaction data and determines if a transaction is fraudulent.
    Implements the FraudService interface defined in the fraud_detection.proto file.
    """

    def _check_card_velocity(self, card_number, correlation_id):
        """
        Check if there have been too many attempts with this card in a time period.
        This helps detect rapid succession of transactions which may indicate fraud.
        
        Args:
            card_number: The credit card number to check
            correlation_id: The request correlation ID for logging
            
        Returns:
            bool: True if the velocity is acceptable, False if too many attempts
        """
        # Hash the card number for privacy
        card_hash = hashlib.sha256(card_number.encode()).hexdigest()
        current_time = time.time()

        # Clean up old entries
        for key in list(FRAUD_ATTEMPT_CACHE.keys()):
            if current_time - FRAUD_ATTEMPT_CACHE[key]['timestamp'] > ATTEMPT_TIMEFRAME:
                del FRAUD_ATTEMPT_CACHE[key]

        # Check current card
        if card_hash in FRAUD_ATTEMPT_CACHE:
            entry = FRAUD_ATTEMPT_CACHE[card_hash]
            entry['count'] += 1
            entry['timestamp'] = current_time

            if entry['count'] > MAX_ATTEMPTS_THRESHOLD:
                logger.warning(f"[{correlation_id}] [Fraud] Velocity check failed for card ending in {card_number[-4:]}")
                return False
        else:
            FRAUD_ATTEMPT_CACHE[card_hash] = {'count': 1, 'timestamp': current_time}

        return True

    def _check_cc_format(self, credit_card):
        """
        Basic validation of credit card format.
        This is a secondary check to ensure the credit card data follows expected patterns.
        
        Args:
            credit_card: CreditCardInfo proto object
            
        Returns:
            bool: True if credit card format is valid, False otherwise
        """
        # Check number length (most cards are between 13-19 digits)
        number = re.sub(r'\D', '', credit_card.number)
        if not (13 <= len(number) <= 19):
            return False

        # Check expiration date format (MM/YY or MM/YYYY)
        if not re.match(r'^(0[1-9]|1[0-2])/(\d{2}|\d{4})$', credit_card.expirationDate):
            return False

        # Check CVV format (3-4 digits)
        if not re.match(r'^\d{3,4}$', credit_card.cvv):
            return False

        return True

    def _initialize_vector_clock(self):
        """
        Initialize vector clock for the service with zero values.
        Includes all services that participate in the distributed transaction.
        
        Returns:
            dict: A dictionary mapping service names to their logical timestamps
        """
        return {
            "transaction_verification": 0,
            "fraud_detection": 0,
            "suggestions": 0
        }

    def InitializeFraudDetection(self, request, context):
        """
        Handles gRPC requests for initializing fraud detection data and caching it.
        This is the first method called in the event-driven flow for the fraud service.
        
        Args:
            request: InitRequest containing order details and initial vector clock
            context: The gRPC context
            
        Returns:
            EventResponse: Contains approval status, message, and updated vector clock
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Initializing fraud detection data for order: {request.order_id}")

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
            "user_info": request.user_info,
            "credit_card": request.credit_card
        }

        # Increment our clock for this initialization
        ORDER_DATA_CACHE[order_id]["vector_clock"][SERVICE_NAME] += 1
        current_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]

        logger.info(f"[{correlation_id}] [Fraud] Fraud detection data cached for order_id: {order_id}")
        logger.info(f"[{correlation_id}] [Fraud] Vector clock: {current_clock}")

        # Create response with updated vector clock
        response = fraud_detection.EventResponse()
        response.approved = True
        response.message = "Fraud detection data initialized successfully"
        
        # Convert Python dict to protobuf map
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time

        return response

    def CheckUserData(self, request, context):
        """
        Handles verification of user data for fraud indicators (Event d).
        Checks if user data shows suspicious patterns.
        
        Args:
            request: EventRequest containing order_id and vector clock
            context: The gRPC context
            
        Returns:
            EventResponse: Contains approval status, message, and updated vector clock
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Checking user data for fraud (Event d).")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             logger.error(f"[{correlation_id}] [Fraud] Order ID {order_id} not found in cache.")
             context.set_code(grpc.StatusCode.NOT_FOUND)
             context.set_details(f"Order ID {order_id} not found.")
             response = fraud_detection.EventResponse()
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

        logger.info(f"[{correlation_id}] [Fraud] Vector clock for {order_id}: {current_clock}")

        # Perform the actual check using cached data
        credit_card = ORDER_DATA_CACHE[order_id]["credit_card"]
        user_info = ORDER_DATA_CACHE[order_id]["user_info"] # Needed for AI prompt
        logging.info(f"CRIEDT CARD: {credit_card.number} {credit_card.expirationDate} {credit_card.cvv}")
        # Create response with updated vector clock
        response = fraud_detection.EventResponse()
        try:
            # Step 1: Send all data to AI for advanced pattern detection
            masked_cc = f"{'*' * (len(credit_card.number) - 4)}{credit_card.number[-4:]}"
            logger.info(f"[{correlation_id}] [Fraud] Initial checks passed; initiating AI analysis for card ending in {credit_card.number[-4:]}")
            prompt = (
                f"As a fraud detection system, analyze this transaction for possible fraud indicators:\n\n"
                f"User: {user_info.name}\n"
                f"Contact: {user_info.contact}\n"
                f"Credit Card: Last 4 digits {credit_card.number[-4:]}\n"
                f"Card Expiration: {credit_card.expirationDate}\n\n"
                f"Common fraud indicators include:\n"
                f"- Mismatched names/emails\n"
                f"- Suspicious email patterns\n"
                f"- Unusual character patterns\n"
                f"- Geographic inconsistencies\n\n"
                "Please respond with JSON in the following format (use valid JSON booleans and numbers):\n"
                "{\n"
                '  "approved": true,  // or false\n'
                '  "confidence": 0.95,  // a number between 0 and 1\n'
                '  "reason": "Explanation if rejected, otherwise empty string"\n'
                "}"
            )

            ai_response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a fraud detection AI specialized in identifying transaction fraud patterns."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Lower temperature for consistent responses
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            ai_message = ai_response.choices[0].message.content.strip()

            try:
                result_json = json.loads(ai_message)
                is_approved = result_json.get("approved", False)
                confidence = result_json.get("confidence", 0.0)
                reason = result_json.get("reason", "")

                if not is_approved and confidence > 0.7:
                    logger.info(f"[{correlation_id}] [Fraud] Transaction rejected by AI (confidence {confidence}): {reason}")

                if not is_approved and confidence <= 0.7:
                    logger.info(f"[{correlation_id}] [Fraud] AI flagged issues (low confidence {confidence}): {reason}")
                    is_approved = True  # Potentially still approve but log the warning

            except json.JSONDecodeError:
                logger.error(f"[{correlation_id}] [Fraud] Failed to parse AI response: {ai_message}")
                response.approved = is_approved
                response.message = "AI response parsing error"
                for service, time in current_clock.items():
                    response.vector_clock.clock[service] = time 
                return response
        except Exception as e:
            logger.exception(f"[{correlation_id}] [Fraud] Exception during user data check: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in fraud detection service during user data check")
            is_approved = False
            message = f"Internal error: {str(e)}"
            response.approved = is_approved
            response.message = message
            for service, time in current_clock.items():
                response.vector_clock.clock[service] = time
            return response
        message = reason
        user_info = ORDER_DATA_CACHE[order_id]["user_info"]

        logger.info(f"[{correlation_id}] [Fraud] User data check for {user_info.name} completed. Approved: {is_approved}")

        response.approved = is_approved
        response.message = message
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time

        return response

    def CheckCreditCardData(self, request, context):
        """
        Handles gRPC requests for checking credit card data for fraud (Event e).
        Uses EventRequest and EventResponse.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Checking credit card data for fraud (Event e).")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             logger.error(f"[{correlation_id}] [Fraud] Order ID {order_id} not found in cache.")
             context.set_code(grpc.StatusCode.NOT_FOUND)
             context.set_details(f"Order ID {order_id} not found.")
             response = fraud_detection.EventResponse()
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

        logger.info(f"[{correlation_id}] [Fraud] Vector clock for {order_id}: {current_clock}")

        # Perform the actual check using cached data
        credit_card = ORDER_DATA_CACHE[order_id]["credit_card"]
        user_info = ORDER_DATA_CACHE[order_id]["user_info"] # Needed for AI prompt

        response = fraud_detection.EventResponse()
        try:
            # Step 1: Check velocity/frequency of card usage
            if not self._check_card_velocity(credit_card.number, correlation_id):
                logger.warning(f"[{correlation_id}] [Fraud] Card velocity check failed")
                response.approved = False
                response.message = "Card velocity check failed"
                for service, time in current_clock.items():
                    response.vector_clock.clock[service] = time
                return response
        except Exception as e:
            logger.exception(f"[{correlation_id}] [Fraud] Exception during card velocity check: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in fraud detection service during card velocity check")
            response.approved = False
            response.message = f"Internal error: {str(e)}"
            for service, time in current_clock.items():
                response.vector_clock.clock[service] = time
            return response

        response.approved = True
        logger.info(f"[{correlation_id}] [Fraud] Credit card data check completed. Approved: {response.approved}")
        message = "Credit card data check completed successfully."
        response.message = message
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time

        return response

    def ClearFraudCache(self, request, context):
        """
        Clears cached fraud detection data for a completed order.
        Ensures vector clock causality is maintained before removing data.
        
        Args:
            request: ClearCacheRequest containing order_id and final vector clock
            context: The gRPC context
            
        Returns:
            ClearCacheResponse: Contains success status and message
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Clearing fraud cache for order: {request.order_id}")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.warning(f"[{correlation_id}] [Fraud] Order ID {order_id} not found in cache for clearing.")
            response = fraud_detection.ClearCacheResponse()
            response.success = True # Consider it a success if it's already gone
            response.message = f"Order ID {order_id} not found in cache"
            return response

        # Check if our vector clock is <= the final vector clock before clearing
        final_clock = {k: v for k, v in request.final_vector_clock.clock.items()}
        local_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]

        is_safe_to_clear = True
        for service, time in local_clock.items():
            if time > final_clock.get(service, 0):
                is_safe_to_clear = False
                logger.warning(f"[{correlation_id}] [Fraud] Vector clock conflict for clearing: local {service}={time} > final {service}={final_clock.get(service, 0)}")
                break

        response = fraud_detection.ClearCacheResponse()

        if is_safe_to_clear:
            # Safe to clear the cache - all events are captured in the final clock
            del ORDER_DATA_CACHE[order_id]
            response.success = True
            response.message = f"Order ID {order_id} cleared from fraud cache"
            logger.info(f"[{correlation_id}] [Fraud] Order ID {order_id} cleared from cache")
        else:
            # Vector clock conflict - we have local events not reflected in final clock
            response.success = False
            response.message = f"Vector clock conflict for clearing order ID {order_id}"
            logger.warning(f"[{correlation_id}] [Fraud] Vector clock conflict for clearing order ID {order_id}")

        return response

    def DetectFraud(self, request, context):
        """
        Legacy method for fraud detection.
        Kept for backward compatibility but new event-based methods are preferred.
        
        Args:
            request: FraudRequest containing transaction data
            context: The gRPC context
            
        Returns:
            FraudResponse: Contains approval status and message
        """
        # Extract correlation ID from metadata (if available)
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Legacy DetectFraud request received for user: {request.user_info.name}")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             # If not initialized, cache basic info and an initial clock
             ORDER_DATA_CACHE[order_id] = {
                 "request": request,
                 "vector_clock": self._initialize_vector_clock(),
                 "user_info": request.user_info,
                 "credit_card": request.credit_card
             }
             logger.info(f"[{correlation_id}] [Fraud] Legacy request: Order data cached for order_id: {order_id}")
        else:
             logger.info(f"[{correlation_id}] [Fraud] Legacy request: Order data already cached for order_id: {order_id}")

        response = fraud_detection.FraudResponse()
        response.approved = True # Indicate successful caching/receipt, not final approval
        response.message = "Legacy fraud detection process initiated (caching only)."

        return response


def serve():
    """
    Starts the gRPC server and listens for incoming fraud detection requests.
    Uses ThreadPoolExecutor to handle concurrent requests.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service = FraudService()
    fraud_detection_grpc.add_FraudServiceServicer_to_server(service, server)
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"Fraud Detection Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
