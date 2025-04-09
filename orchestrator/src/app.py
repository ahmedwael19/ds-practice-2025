"""
Orchestrator Service

This module implements an API gateway using Flask to orchestrate multiple gRPC services.
It integrates with:
    - Fraud Detection Service: Validates transactions for fraudulent activity.
    - Transaction Verification Service: Ensures credit card and item validity.
    - Book Suggestions Service: Provides book recommendations based on purchases.

The service receives checkout requests, invokes the required gRPC services concurrently,
and returns an order status along with book recommendations if the order is approved.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-03-07
"""

import os
import sys
import json
import time
import uuid
import grpc
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from random import randrange
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.protobuf.json_format import MessageToDict

# Set up paths for gRPC service stubs
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")

fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2, fraud_detection_pb2_grpc

transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2, transaction_verification_pb2_grpc

suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2, suggestions_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("orchestrator")

# Initialize Flask app and enable CORS
app = Flask(__name__)
CORS(app, resources={r'/*': {'origins': '*'}})

def generate_correlation_id():
    """Generates a unique correlation ID for request tracking in logs."""
    return f"{time.strftime('%Y%m%d%H%M%S')}-{randrange(1000, 9999)}"

def call_fraud_detection(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    logger.info(f"[{cid}] [Orchestrator] Calling Fraud Detection service.")
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        response = stub.DetectFraud(
            fraud_detection_pb2.FraudRequest(
                order_id=order_data["orderId"],
                user_info=order_data.get("user", {}),
                credit_card=order_data.get("creditCard", {})
            ),
            metadata=(("correlation-id", cid),)
        )
    logger.info(f"[{cid}] [Orchestrator] Fraud Detection response received.")
    return {"fraud_detection": response}

def call_transaction_verification(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    logger.info(f"[{cid}] [Orchestrator] Calling Transaction Verification service.")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        response = stub.VerifyTransaction(
            transaction_verification_pb2.TransactionRequest(
                order_id=order_data["orderId"],
                items=order_data.get("items", []),
                credit_card=order_data.get("creditCard", {})
            ),
            metadata=(("correlation-id", cid),)
        )
    logger.info(f"[{cid}] [Orchestrator] Transaction Verification response received.")
    return {"transaction_verification": response}

def call_suggestions(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    try:
        # Attempt to extract a book name from the order items, fallback to "random"
        book_name = order_data.get("items", [])[0].get("items", {}).get("name", "random")
    except Exception:
        book_name = "random"
    logger.info(f"[{cid}] [Orchestrator] Calling Suggestions service (book: {book_name}).")
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        response = stub.GetSuggestions(
            suggestions_pb2.SuggestionRequest(
                book_name=book_name,
                order_id=order_data["orderId"]
            ),
            metadata=(("correlation-id", cid),)
        )
    logger.info(f"[{cid}] [Orchestrator] Suggestions response received.")
    return {"suggestions": response}

@app.route('/checkout', methods=['POST'])
def checkout():
    cid = generate_correlation_id()
    logger.info(f"[{cid}] [Orchestrator] Checkout request received.")
    try:
        order_data = json.loads(request.data)
        order_data["orderId"] = str(uuid.uuid4())
        order_data["correlation_id"] = cid
        results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures_list = [
                executor.submit(call_fraud_detection, order_data),
                executor.submit(call_transaction_verification, order_data),
                executor.submit(call_suggestions, order_data)
            ]
            for future in as_completed(futures_list):
                results.update(future.result())
                logger.info(f"[{cid}] [Orchestrator] Service thread completed.")

        fraud_response = results.get("fraud_detection", None)
        txn_response = results.get("transaction_verification", None)
        suggestions_response = results.get("suggestions", None)

        if fraud_response and txn_response:
            if fraud_response.approved and txn_response.approved:
                order_status = "Order Approved"
                suggested_books = (
                    [MessageToDict(book) for book in suggestions_response.suggested_books]
                    if suggestions_response and suggestions_response.suggested_books
                    else []
                )
            elif not fraud_response.approved:
                order_status = "Order Rejected: Fraud detection failed"
                suggested_books = []
            elif not txn_response.approved:
                rejection_reason = txn_response.message if txn_response.message else "Transaction verification failed"
                order_status = f"Order Rejected: {rejection_reason}"
                suggested_books = []
        else:
            order_status = "Order Rejected: Service error"
            suggested_books = []

        # Always include 'suggestedBooks' (even if empty)
        final_response = {"orderId": order_data["orderId"], "status": order_status, "suggestedBooks": suggested_books if order_status == "Order Approved" else []}

        logger.info(f"[{cid}] [Orchestrator] Checkout completed with response: {final_response}")
        return jsonify(final_response)
    except Exception as e:
        logger.exception(f"[{cid}] [Orchestrator] Error: {str(e)}")
        return jsonify({"error": {"message": "Internal server error"}}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0')
