import sys
import os
import uuid
import json
import grpc
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.protobuf.json_format import MessageToDict

import time
from random import randrange

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

# Custom logging format for better readability
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("orchestrator")

app = Flask(__name__)
CORS(app, resources={r'/*': {'origins': '*'}})


def generate_correlation_id():
    # Generates an ID in the format YYYYMMDDHHMMSS-RAND, e.g. "20250306122345-1234"
    return f"{time.strftime('%Y%m%d%H%M%S')}-{randrange(1000, 9999)}"

# Note: Instead of generating a new id in every helper, we use the one attached
# to order_data from the /checkout endpoint.
def call_fraud_detection(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    logger.info(f"[{cid}] Calling fraud_detection service")
    user_info = order_data.get("user", {})
    credit_card = order_data.get("creditCard", {})
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        response = stub.DetectFraud(
    fraud_detection_pb2.FraudRequest(user_info=user_info, credit_card=credit_card),
    metadata=(("correlation-id", cid),)
)
    logger.info(f"[{cid}] fraud_detection response received")
    return {"fraud_detection": response}

def call_transaction_verification(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    logger.info(f"[{cid}] Calling transaction_verification service")
    item_list = order_data.get("items", [])
    credit_card = order_data.get("creditCard", {})
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        response = stub.VerifyTransaction(transaction_verification_pb2.TransactionRequest(items=item_list, credit_card=credit_card),
    metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] transaction_verification response received")
    return {"transaction_verification": response}

def call_suggestions(order_data):
    cid = order_data.get("correlation_id", generate_correlation_id())
    try:
        # Expecting order_data["items"][0]["items"]["name"]
        book_name = order_data.get("items", [])[0].get("items", {}).get("name", "random")
    except Exception:
        book_name = "random"
    logger.info(f"[{cid}] Calling suggestions service with book_name: {book_name}")
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        response = stub.GetSuggestions(suggestions_pb2.SuggestionRequest(book_name=book_name),
    metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] suggestions service response received")
    return {"suggestions": response}

@app.route('/checkout', methods=['POST'])
def checkout():
    cid = generate_correlation_id()
    logger.info(f"[{cid}] Received checkout request")
    try:
        order_data = json.loads(request.data)
        # Attach the same correlation id to order_data so that helper functions reuse it.
        order_data["correlation_id"] = cid

        results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(call_fraud_detection, order_data),
                executor.submit(call_transaction_verification, order_data),
                executor.submit(call_suggestions, order_data)
            ]
            for future in as_completed(futures):
                results.update(future.result())
                logger.info(f"[{cid}] One service thread completed")

        order_status = "Order Approved"
        if not results.get("fraud_detection", {}).approved or not results.get("transaction_verification", {}).approved:
            order_status = "Order Rejected"
        suggested_json = []
        if order_status == "Order Approved":
            suggested_json = [MessageToDict(book) for book in results['suggestions'].suggested_books]
        final_response = {
            "orderId": "12345",
            "status": order_status,
            "suggestedBooks": suggested_json
        }
        logger.info(f"[{cid}] Checkout completed with response: {final_response}")
        return jsonify(final_response)
    except Exception as e:
        logger.exception(f"[{cid}] Error processing checkout: {str(e)}")
        return jsonify({"error": {"message": "Internal server error"}}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0')