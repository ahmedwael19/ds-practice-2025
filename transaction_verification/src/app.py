"""
Transaction Verification Service

This module implements a gRPC service that verifies transactions.
It performs comprehensive validation on transaction data, including items, shipping methods,
discount codes, and ensures all required transaction information is present and valid.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-03-07
"""

import os
import sys
import grpc
import logging
import re
import threading
import copy
from concurrent import futures
from datetime import datetime

import re
import datetime
# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2
import transaction_verification_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("transaction_verification")

ORDER_DATA_CACHE = {}
SERVICE_NAME = "transaction_verification"

def merge_clocks(local_clock, received_clock):
    """Merges two vector clocks, taking the maximum value for each entry."""
    merged = local_clock.copy()
    for service, time in received_clock.items():
        merged[service] = max(merged.get(service, 0), time)
    return merged
 
class TransactionService(transaction_verification_pb2_grpc.TransactionServiceServicer):
    """
    gRPC Service for transaction verification.
    It validates transaction data, ensuring all required fields are present and correctly formatted.
    """

    def _validate_items(self, items):
        """
        Validate that the items list contains valid items.
        """
        if not items:
            logger.info("No items provided in transaction.")
            return False

        for item in items:
            if not item.name or len(item.name.strip()) == 0:
                logger.info("Item missing name.")
                return False
            if item.quantity <= 0:
                logger.info(f"Invalid quantity for item: {item.name}.")
                return False
        return True


    def _validate_cc_format(self, credit_card):
        """
        Validate basic credit card format including:
        - Number length (13-19 digits)
        - Expiration date format (MM/YY or MM/YYYY) and not expired
        - CVV format (3-4 digits)
        """
        # Validate credit card number length
        number = re.sub(r'\D', '', credit_card.number)
        if not (13 <= len(number) <= 19):
            return False

        # Validate expiration date format (MM/YY or MM/YYYY)
        exp_date = credit_card.expirationDate
        match = re.match(r'^(0[1-9]|1[0-2])/(\d{2}|\d{4})$', exp_date)
        if not match:
            return False

        # Check if the expiration date is in the future
        month = int(match.group(1))
        year = int(match.group(2))
        # Convert two-digit year to four digits
        if len(match.group(2)) == 2:
            year += 2000

        # Create a date for the last day of the expiration month
        # One approach is to set the day to the first of the month after expiration and then subtract a day
        if month == 12:
            exp_year = year + 1
            exp_month = 1
        else:
            exp_year = year
            exp_month = month + 1
        try:
            exp_date_obj = datetime.date(exp_year, exp_month, 1) - datetime.timedelta(days=1)
        except ValueError:
            return False

        # Check against today's date
        if exp_date_obj < datetime.date.today():
            return False

        # Validate CVV (3-4 digits)
        if not re.match(r'^\d{3,4}$', credit_card.cvv):
            return False

        return True

    def _validate_luhn(self, card_number):
        """
        Validate credit card number using the Luhn algorithm.
        """
        digits = [int(d) for d in card_number if d.isdigit()]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9:
                digits[i] -= 9
        return sum(digits) % 10 == 0

    def _initialize_vector_clock(self):
        """
        Initialize vector clock for the service
        """
        return {
            "transaction_verification": 0,
            "fraud_detection": 0,
            "suggestions": 0}

    def _validate_credit_card_format(self, credit_card):
        """
        Validate credit card format (not content - that's fraud detection's job).
        """
        if not credit_card.number or not re.match(r'^\d{16}$', credit_card.number):
            logger.info("Invalid credit card number format.")
            return False

        if not credit_card.expirationDate or not re.match(r'^(0[1-9]|1[0-2])/(\d{2}|\d{4})$', credit_card.expirationDate):
            logger.info("Invalid credit card expiration date format.")
            return False

        if not credit_card.cvv or not re.match(r'^\d{3,4}$', credit_card.cvv):
            logger.info("Invalid credit card CVV format.")
            return False
 
        return True

    def VerifyItems(self, request, context):
        """
        Handles gRPC requests for verifying items.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                  if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Verifying items.")

        order_id = request.order_id
        vector_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        vector_clock["transaction_verification"] += 1
        logger.info(f"[{correlation_id}] [Verification] Vector clock: {vector_clock}")

        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True

        # Validate items
        if not self._validate_items(request.items):
            logger.info(f"[{correlation_id}] [Verification] Item validation failed.")
            response.approved = False
            response.message = "Invalid items in cart"
            return response

        logger.info(f"[{correlation_id}] [Verification] Items verified. Approved: {response.approved}")
        return response

    def VerifyUserData(self, request, context):
        """
        Handles gRPC requests for verifying user data.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Verifying user data.")

        order_id = request.order_id
        vector_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        vector_clock["transaction_verification"] += 1
        logger.info(f"[{correlation_id}] [Verification] Vector clock: {vector_clock}")

        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True

        #TODO: Implement user data validation
        logger.info(f"[{correlation_id}] [Verification] User data verified. Approved: {response.approved}")
        return response


    def InitializeTransaction(self, request, context):
        """
        Handles gRPC requests for initializing transaction data and caching it.
        This is the first call in the new event-driven flow.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Initializing transaction data for order: {request.order_id}")
        
        order_id = request.order_id
        
        # Initialize vector clock, potentially merging with incoming clock
        vector_clock = self._initialize_vector_clock()
        if hasattr(request, 'vector_clock') and request.vector_clock:
            # Convert from protobuf map to Python dict
            incoming_clock = {k: v for k, v in request.vector_clock.clock.items()}
            vector_clock = merge_clocks(vector_clock, incoming_clock)
        
        # Cache the request data and vector clock
        ORDER_DATA_CACHE[order_id] = {
            "request": request,
            "vector_clock": vector_clock,
            "items": request.items,
            "credit_card": request.credit_card,
            "user_name": request.user_name,
            "user_contact": request.user_contact
        }
        
        # Increment our clock for this initialization
        ORDER_DATA_CACHE[order_id]["vector_clock"][SERVICE_NAME] += 1
        current_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        
        logger.info(f"[{correlation_id}] [Verification] Transaction data cached for order_id: {order_id}")
        logger.info(f"[{correlation_id}] [Verification] Vector clock: {current_clock}")
        
        # Create response with updated vector clock
        response = transaction_verification_pb2.EventResponse()
        response.approved = True
        response.message = "Transaction data initialized successfully"
        
        # Convert Python dict to protobuf map
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time
            
        return response
        
    def VerifyItems(self, request, context):
        """
        Handles gRPC requests for verifying items (Event a).
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Verifying items (Event a).")
        
        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.error(f"[{correlation_id}] [Verification] Order ID {order_id} not found in cache.")
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Order ID {order_id} not found.")
            response = transaction_verification_pb2.EventResponse()
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
        
        logger.info(f"[{correlation_id}] [Verification] Vector clock for {order_id}: {current_clock}")
        
        # Validate items
        items = ORDER_DATA_CACHE[order_id]["items"]
        is_valid = self._validate_items(items)
        
        # Create response with updated vector clock
        response = transaction_verification_pb2.EventResponse()
        response.approved = is_valid
        
        if not is_valid:
            response.message = "Invalid items in cart"
            logger.info(f"[{correlation_id}] [Verification] Item validation failed.")
        else:
            response.message = "Items verified successfully"
            logger.info(f"[{correlation_id}] [Verification] Items verified successfully.")
            
        # Convert Python dict to protobuf map
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time
            
        return response
        
    def VerifyUserData(self, request, context):
        """
        Handles gRPC requests for verifying user data (Event b).
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Verifying user data (Event b).")
        
        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.error(f"[{correlation_id}] [Verification] Order ID {order_id} not found in cache.")
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Order ID {order_id} not found.")
            response = transaction_verification_pb2.EventResponse()
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
        
        logger.info(f"[{correlation_id}] [Verification] Vector clock for {order_id}: {current_clock}")
        
        # Validate user data
        user_name = ORDER_DATA_CACHE[order_id].get("user_name", "")
        user_contact = ORDER_DATA_CACHE[order_id].get("user_contact", "")
        
        is_valid = bool(user_name and user_contact)
        
        # Create response with updated vector clock
        response = transaction_verification_pb2.EventResponse()
        response.approved = is_valid
        
        if not is_valid:
            response.message = "Missing required user data"
            logger.info(f"[{correlation_id}] [Verification] User data validation failed.")
        else:
            response.message = "User data verified successfully"
            logger.info(f"[{correlation_id}] [Verification] User data verified successfully.")
            
        # Convert Python dict to protobuf map
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time
            
        return response
        
    def VerifyCreditCardFormat(self, request, context):
        """
        Handles gRPC requests for verifying credit card format (Event c).
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Verifying credit card format (Event c).")
        
        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.error(f"[{correlation_id}] [Verification] Order ID {order_id} not found in cache.")
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Order ID {order_id} not found.")
            response = transaction_verification_pb2.EventResponse()
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
        
        logger.info(f"[{correlation_id}] [Verification] Vector clock for {order_id}: {current_clock}")
        
        # Validate credit card format
        credit_card = ORDER_DATA_CACHE[order_id]["credit_card"]
        is_valid = self._validate_credit_card_format(credit_card) and self._validate_cc_format(credit_card)
        
        # Create response with updated vector clock
        response = transaction_verification_pb2.EventResponse()
        response.approved = is_valid
        
        if not is_valid:
            response.message = "Invalid credit card format"
            logger.info(f"[{correlation_id}] [Verification] Credit card format validation failed.")
        else:
            response.message = "Credit card format verified successfully"
            logger.info(f"[{correlation_id}] [Verification] Credit card format verified successfully.")
            
        # Convert Python dict to protobuf map
        for service, time in current_clock.items():
            response.vector_clock.clock[service] = time
            
        return response
        
    def ClearTransactionCache(self, request, context):
        """
        Handles gRPC requests for clearing cached transaction data.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Clearing transaction cache for order: {request.order_id}")
        
        order_id = request.order_id
        if order_id not in ORDER_DATA_CACHE:
            logger.warning(f"[{correlation_id}] [Verification] Order ID {order_id} not found in cache.")
            response = transaction_verification_pb2.ClearCacheResponse()
            response.success = True  # Consider it a success if it's already gone
            response.message = f"Order ID {order_id} not found in cache"
            return response
            
        # Check if our vector clock is <= the final vector clock
        final_clock = {k: v for k, v in request.final_vector_clock.clock.items()}
        local_clock = ORDER_DATA_CACHE[order_id]["vector_clock"]
        
        is_safe_to_clear = True
        for service, time in local_clock.items():
            if time > final_clock.get(service, 0):
                is_safe_to_clear = False
                logger.warning(f"[{correlation_id}] [Verification] Vector clock conflict: local {service}={time} > final {service}={final_clock.get(service, 0)}")
                break
                
        response = transaction_verification_pb2.ClearCacheResponse()
        
        if is_safe_to_clear:
            # Safe to clear the cache
            del ORDER_DATA_CACHE[order_id]
            response.success = True
            response.message = f"Order ID {order_id} cleared from cache"
            logger.info(f"[{correlation_id}] [Verification] Order ID {order_id} cleared from cache")
        else:
            # Vector clock conflict
            response.success = False
            response.message = f"Vector clock conflict for order ID {order_id}"
            logger.warning(f"[{correlation_id}] [Verification] Vector clock conflict for order ID {order_id}")
            
        return response
    
    def VerifyTransaction(self, request, context):
        """
        Handles gRPC requests for transaction verification.
        This is the original method, kept for backward compatibility.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                  if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Legacy VerifyTransaction request received.")

        order_id = request.order_id

        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True

        # Validate credit card format
        if not self._validate_credit_card_format(request.credit_card):
            logger.info(f"[{correlation_id}] [Verification] Credit card format validation failed.")
            response.approved = False
            response.message = "Invalid credit card format"
            return response

        # Validate credit card expiry date
        if not self._validate_cc_format(request.credit_card):
            logger.info(f"[{correlation_id}] [Verification] Credit card date validation failed.")
            response.approved = False
            response.message = "Invalid credit card date"
            return response
        # Validate credit card number with Luhn algorithm
        if not self._validate_luhn(request.credit_card.number):
            logger.warning(f"[{correlation_id}] [Verification] Luhn check failed.")
            response.approved = False
            response.message = "Credit card failed Luhn check"
            return response

        logger.info(f"[{correlation_id}] [Verification] Completed. Approved: {response.approved}")
        return response

def serve():
    """
    Starts the gRPC server and listens for incoming transaction verification requests.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionServiceServicer_to_server(TransactionService(), server)
    port = "50052"
    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"Transaction Verification Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
