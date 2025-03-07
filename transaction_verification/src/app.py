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

    def VerifyTransaction(self, request, context):
        """
        Handles gRPC requests for transaction verification.
        """
        correlation_id = next((value for key, value in context.invocation_metadata()
                                 if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] [Verification] Request received.")

        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True

        # Validate items
        if not self._validate_items(request.items):
            logger.info(f"[{correlation_id}] [Verification] Item validation failed.")
            response.approved = False
            response.message = "Invalid items in cart"
            return response

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
