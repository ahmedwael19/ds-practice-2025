"""
Fraud Detection Service

This module implements a gRPC service that evaluates transactions for potential fraud.
It integrates with OpenAI's GPT model and uses additional rules to determine whether a transaction is fraudulent.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-03-07
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

# Cache for tracking repeated fraud attempts (simple in-memory implementation)
FRAUD_ATTEMPT_CACHE = {}
# Maximum number of attempts within timeframe
MAX_ATTEMPTS_THRESHOLD = 5
# Timeframe in seconds (1 hour)
ATTEMPT_TIMEFRAME = 3600

ORDER_DATA_CACHE = {}

class FraudService(fraud_detection_grpc.FraudServiceServicer):
    """
    gRPC Service that evaluates transaction data and determines if a transaction is fraudulent.
    """

    def _check_card_velocity(self, card_number, correlation_id):
        """
        Check if there have been too many attempts with this card in a time period.
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
        Initialize vector clock for the service
        """
        return {
            "transaction_verification": 0,
            "fraud_detection": 0,
            "suggestions": 0
        }

    def CheckUserData(self, request, context):
        """
        Handles gRPC requests for checking user data for fraud. (Event d)
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Checking user data for fraud (Event d).")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             logger.error(f"[{correlation_id}] [Fraud] Order ID {order_id} not found in cache.")
             context.set_code(grpc.StatusCode.NOT_FOUND)
             context.set_details(f"Order ID {order_id} not found.")
             return fraud_detection.FraudResponse(approved=False)

        vector_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        vector_clock["fraud_detection"] += 1
        logger.info(f"[{correlation_id}] [Fraud] Vector clock for {order_id}: {vector_clock}")

        response = fraud_detection.FraudResponse()
        # Reuse existing AI logic for user data check (simplified for this example)
        # In a real scenario, this might be a separate, more focused check
        # For now, we'll just log and approve
        logger.info(f"[{correlation_id}] [Fraud] User data check for {request.user_info.name} completed.")
        response.approved = True
        return response

    def CheckCreditCardData(self, request, context):
        """
        Handles gRPC requests for checking credit card data for fraud. (Event e)
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Checking credit card data for fraud (Event e).")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
             logger.error(f"[{correlation_id}] [Fraud] Order ID {order_id} not found in cache.")
             context.set_code(grpc.StatusCode.NOT_FOUND)
             context.set_details(f"Order ID {order_id} not found.")
             return fraud_detection.FraudResponse(approved=False)

        vector_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        vector_clock["fraud_detection"] += 1
        logger.info(f"[{correlation_id}] [Fraud] Vector clock for {order_id}: {vector_clock}")

        response = fraud_detection.FraudResponse()

        try:
            # Step 1: Check velocity/frequency of card usage
            if not self._check_card_velocity(request.credit_card.number, correlation_id):
                logger.warning(f"[{correlation_id}] [Fraud] Card velocity check failed")
                response.approved = False
                return response

            # Step 2: Send to AI for advanced pattern detection (reusing the existing logic)
            masked_cc = f"{'*' * (len(request.credit_card.number) - 4)}{request.credit_card.number[-4:]}"
            logger.info(f"[{correlation_id}] [Fraud] Initial checks passed; initiating AI analysis for card ending in {request.credit_card.number[-4:]}")

            prompt = (
                f"As a fraud detection system, analyze this transaction for possible fraud indicators:\n\n"
                f"User: {request.user_info.name}\n"
                f"Contact: {request.user_info.contact}\n"
                f"Credit Card: Last 4 digits {request.credit_card.number[-4:]}\n"
                f"Card Expiration: {request.credit_card.expirationDate}\n\n"
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
                approval = result_json.get("approved", False)
                confidence = result_json.get("confidence", 0.0)
                reason = result_json.get("reason", "")

                if not approval and confidence > 0.7:
                    logger.info(f"[{correlation_id}] [Fraud] Transaction rejected by AI (confidence {confidence}): {reason}")
                    response.approved = False
                    return response

                if not approval and confidence <= 0.7:
                    logger.info(f"[{correlation_id}] [Fraud] AI flagged issues (low confidence {confidence}): {reason}")

                response.approved = True
                logger.info(f"[{correlation_id}] [Fraud] Credit card data check completed. Approved: {response.approved}")
                return response

            except json.JSONDecodeError:
                logger.error(f"[{correlation_id}] [Fraud] Failed to parse AI response: {ai_message}")
                response.approved = False
                return response

        except Exception as e:
            logger.exception(f"[{correlation_id}] [Fraud] Exception: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in fraud detection service")
            response.approved = False
            return response

    def DetectFraud(self, request, context):
        """
        Handles gRPC requests for fraud detection. This now acts as the initial entry point
        to cache data and potentially trigger the first event if needed, but the main logic
        is moved to specific event handlers.
        """
        # Extract correlation ID from metadata (if available)
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Fraud] Initial DetectFraud request received for user: {request.user_info.name}")

        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            ORDER_DATA_CACHE[order_id] = {
                "request": request,
                "vector_clock": self._initialize_vector_clock()
            }
            logger.info(f"[{correlation_id}] [Fraud] Order data cached for order_id: {order_id}")
        else:
             logger.info(f"[{correlation_id}] [Fraud] Order data already cached for order_id: {order_id}")

        # This initial call might just confirm receipt and caching.
        # The actual fraud checks are triggered by specific event calls from the orchestrator.
        response = fraud_detection.FraudResponse()
        response.approved = True # Indicate successful caching, not final approval
        response.message = "Fraud detection process initiated."
        return response


def serve():
    """
    Starts the gRPC server and listens for incoming fraud detection requests.
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
