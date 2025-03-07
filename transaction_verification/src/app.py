"""
Transaction Verification Service

This module implements a gRPC service that verifies transactions.
It performs basic validation on transaction data, including credit card number length.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-03-07
"""

import os
import sys
import grpc
import logging
from concurrent import futures

# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2
import transaction_verification_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("transaction_verification")

class TransactionService(transaction_verification_pb2_grpc.TransactionServiceServicer):
    """
    gRPC Service for transaction verification.
    It validates transaction data, including the structure of credit card information.
    """
    
    def VerifyTransaction(self, request, context):
        """
        Handles gRPC requests for transaction verification.
        
        Args:
            request (transaction_verification_pb2.TransactionRequest): The transaction request containing item details and credit card information.
            context (grpc.ServicerContext): gRPC context for handling metadata and errors.
        
        Returns:
            transaction_verification_pb2.TransactionResponse: The response indicating whether the transaction is approved.
        """
        # Extract correlation ID from metadata (if available)
        correlation_id = next((value for key, value in context.invocation_metadata() if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] Received VerifyTransaction request")
        
        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True
        
        # Basic transaction validation: Ensure credit card number has 16 digits
        if request.items and len(request.credit_card.number) != 16:
            logger.info(f"[{correlation_id}] Transaction invalid due to incorrect credit card number length")
            response.approved = False
        
        logger.info(f"[{correlation_id}] VerifyTransaction completed with approved={response.approved}")
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
