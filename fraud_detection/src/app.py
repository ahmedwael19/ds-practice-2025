"""
Fraud Detection Service

This module implements a gRPC service that evaluates transactions for potential fraud.
It integrates with OpenAI's GPT model to determine whether a transaction is fraudulent.

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
from concurrent import futures

# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("fraud_detection")

# Initialize OpenAI API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

class FraudService(fraud_detection_grpc.FraudServiceServicer):
    """
    gRPC Service that evaluates transaction data and determines if a transaction is fraudulent.
    """
    
    def DetectFraud(self, request, context):
        """
        Handles gRPC requests for fraud detection.
        
        Args:
            request (fraud_detection.FraudRequest): The incoming request containing transaction details.
            context (grpc.ServicerContext): gRPC context for handling metadata and errors.
        
        Returns:
            fraud_detection.FraudResponse: The response indicating whether the transaction is approved.
        """
        # Extract correlation ID from metadata (if available)
        correlation_id = next((value for key, value in context.invocation_metadata() if key == "correlation-id"), "N/A")
        logger.info(f"[{correlation_id}] Received DetectFraud request for user: {request.user_info.name}")
        
        response = fraud_detection.FraudResponse()
        try:
            # Construct AI prompt for fraud detection
            prompt = (
                f"Evaluate the following transaction details and determine whether it is fraudulent. "
                f"If all information is present, formatted correctly, and the credit card number follows standard patterns, "
                f"consider the transaction legitimate. Transaction details: "
                f"User: {request.user_info.name}, Contact: {request.user_info.contact}. "
                f"Credit Card: Number: {request.credit_card.number}, "
                f"Expiration: {request.credit_card.expirationDate}, CVV: {request.credit_card.cvv}. "
                "Respond ONLY with JSON in the format: {\"approved\": true} if legitimate, "
                "or {\"approved\": false} if fraudulent."
            )
            
            logger.info(f"[{correlation_id}] Sending prompt to OpenAI for fraud detection: {prompt}")
            
            # Call OpenAI API for fraud evaluation
            ai_response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a fraud detection AI."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=50
            )
            
            ai_message = ai_response.choices[0].message.content.strip()
            
            # Parse AI response into JSON format
            try:
                result_json = json.loads(ai_message)
            except json.JSONDecodeError:
                logger.error(f"[{correlation_id}] Failed to parse AI response: {ai_message}")
                result_json = {"approved": False}  # Default to rejection if parsing fails
            
            response.approved = result_json.get("approved", False)
            logger.info(f"[{correlation_id}] Fraud detection result: approved={response.approved}")
            return response
        
        except Exception as e:
            logger.exception(f"[{correlation_id}] Exception in DetectFraud: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error in fraud detection service")
            response.approved = False
            return response


def serve():
    """
    Starts the gRPC server and listens for incoming fraud detection requests.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    fraud_detection_grpc.add_FraudServiceServicer_to_server(FraudService(), server)
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"Fraud Detection Service started on port {port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
