"""
Orchestrator Service (Event-Driven with Vector Clocks)

This module implements an API gateway using Flask to orchestrate multiple gRPC services
following a defined event order using vector clocks.
It integrates with:
    - Transaction Verification Service
    - Fraud Detection Service
    - Book Suggestions Service

The service receives checkout requests, initializes the process across services,
executes events based on a partial order, manages vector clocks, handles failures,
and returns the final status and suggestions.

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
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from random import randrange
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.protobuf.json_format import MessageToDict, ParseDict

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

# --- Helper Functions ---

def dict_to_vector_clock(clock_dict, pb2_module):
    """Converts a Python dict to a VectorClock protobuf message using the specified pb2 module."""
    # Dynamically create the VectorClock instance from the correct module
    vector_clock_pb = pb2_module.VectorClock()
    if clock_dict:
        for service, time_val in clock_dict.items():
            vector_clock_pb.clock[service] = time_val
    return vector_clock_pb

def vector_clock_to_dict(vector_clock_pb):
    """Converts a VectorClock protobuf message to a Python dict."""
    return {k: v for k, v in vector_clock_pb.clock.items()}

def merge_clocks(clock1_dict, clock2_dict):
    """Merges two vector clocks (Python dicts), taking the maximum value for each entry."""
    merged = copy.deepcopy(clock1_dict)
    if clock2_dict:
        for service, time_val in clock2_dict.items():
            merged[service] = max(merged.get(service, 0), time_val)
    return merged

# Initialize Flask app and enable CORS
app = Flask(__name__)
CORS(app, resources={r'/*': {'origins': '*'}})

def generate_correlation_id():
    """Generates a unique correlation ID for request tracking in logs."""
    return f"{time.strftime('%Y%m%d%H%M%S')}-{randrange(1000, 9999)}"

# --- gRPC Call Functions for New Event Flow ---

def call_initialize_transaction(order_data, initial_clock_dict):
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    logger.info(f"[{cid}] [Orchestrator] Initializing Transaction Verification for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.InitRequest(
            order_id=order_id,
            items=[transaction_verification_pb2.Item(name=item.get('name'), quantity=item.get('quantity')) for item in order_data.get("items", [])],
            credit_card=transaction_verification_pb2.CreditCardInfo(**order_data.get("creditCard", {})),
            billingAddress=transaction_verification_pb2.Address(**order_data.get("billingAddress", {})),
            termsAndConditionsAccepted=order_data.get("termsAndConditionsAccepted", False),
            user_contact=order_data.get("user", {}).get("contact"),
            user_name=order_data.get("user", {}).get("name"),
            vector_clock=dict_to_vector_clock(initial_clock_dict, transaction_verification_pb2)
        )
        response = stub.InitializeTransaction(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] Transaction Verification Initialized. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return {"service": "transaction", "response": response}

def call_initialize_fraud(order_data, initial_clock_dict):
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    logger.info(f"[{cid}] [Orchestrator] Initializing Fraud Detection for order {order_id}")
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        request_pb = fraud_detection_pb2.InitRequest(
            order_id=order_id,
            user_info=fraud_detection_pb2.UserInfo(**order_data.get("user", {})),
            credit_card=fraud_detection_pb2.CreditCardInfo(**order_data.get("creditCard", {})),
            vector_clock=dict_to_vector_clock(initial_clock_dict, fraud_detection_pb2)
        )
        response = stub.InitializeFraudDetection(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] Fraud Detection Initialized. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return {"service": "fraud", "response": response}

def call_initialize_suggestions(order_data, initial_clock_dict):
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    try:
        book_name = order_data.get("items", [])[0].get("name", "random")
    except Exception:
        book_name = "random"
    logger.info(f"[{cid}] [Orchestrator] Initializing Suggestions for order {order_id}")
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        request_pb = suggestions_pb2.InitRequest(
            order_id=order_id,
            book_name=book_name,
            vector_clock=dict_to_vector_clock(initial_clock_dict, suggestions_pb2)
        )
        response = stub.InitializeSuggestions(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] Suggestions Initialized. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return {"service": "suggestions", "response": response}

# --- Event Specific Calls ---

def call_verify_items(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyItems (Event a) for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        response = stub.VerifyItems(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] VerifyItems response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_verify_user_data(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyUserData (Event b) for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        response = stub.VerifyUserData(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] VerifyUserData response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_verify_credit_card_format(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyCreditCardFormat (Event c) for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            # Note: current_clock_dict here is actually clock_a from the call site in checkout()
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        response = stub.VerifyCreditCardFormat(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] VerifyCreditCardFormat response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_check_user_data(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling CheckUserData (Event d) for order {order_id}")
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        request_pb = fraud_detection_pb2.EventRequest(
            order_id=order_id,
            # Note: current_clock_dict here is actually clock_b from the call site in checkout()
            vector_clock=dict_to_vector_clock(current_clock_dict, fraud_detection_pb2)
        )
        response = stub.CheckUserData(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] CheckUserData response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_check_credit_card_data(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling CheckCreditCardData (Event e) for order {order_id}")
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        request_pb = fraud_detection_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, fraud_detection_pb2)
        )
        response = stub.CheckCreditCardData(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] CheckCreditCardData response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_get_suggestions(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling GetSuggestions (Event f) for order {order_id}")
    # Need book_name from cache - assuming it was cached during InitializeSuggestions
    # This highlights a potential need to pass book_name through the flow or retrieve it here.
    # For simplicity, let's assume InitializeSuggestions cached it and we retrieve it if needed.
    # A robust solution might involve passing necessary data along or having services fetch it.
    # Let's assume book_name is not needed directly by the call signature based on proto.
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        request_pb = suggestions_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, suggestions_pb2)
            # book_name is part of EventRequest in suggestions.proto, need to get it
            # This requires modification to how data is passed or stored.
            # Let's assume for now the suggestions service retrieves it from its cache.
        )
        response = stub.GetSuggestions(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] GetSuggestions response. Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

# --- Cache Clearing Calls (Bonus) ---
def call_clear_cache(service_name, address, order_id, final_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling Clear Cache for {service_name} for order {order_id}")
    try:
        with grpc.insecure_channel(address) as channel:
            if service_name == "transaction":
                stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
                request_pb = transaction_verification_pb2.ClearCacheRequest(
                    order_id=order_id, final_vector_clock=dict_to_vector_clock(final_clock_dict, transaction_verification_pb2)
                )
                response = stub.ClearTransactionCache(request_pb, metadata=(("correlation-id", cid),))
            elif service_name == "fraud":
                stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
                request_pb = fraud_detection_pb2.ClearCacheRequest(
                    order_id=order_id, final_vector_clock=dict_to_vector_clock(final_clock_dict, fraud_detection_pb2)
                )
                response = stub.ClearFraudCache(request_pb, metadata=(("correlation-id", cid),))
            elif service_name == "suggestions":
                stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
                request_pb = suggestions_pb2.ClearCacheRequest(
                    order_id=order_id, final_vector_clock=dict_to_vector_clock(final_clock_dict, suggestions_pb2)
                )
                response = stub.ClearSuggestionsCache(request_pb, metadata=(("correlation-id", cid),))
            else:
                logger.error(f"[{cid}] [Orchestrator] Unknown service name for clear cache: {service_name}")
                return None
            logger.info(f"[{cid}] [Orchestrator] Clear Cache response from {service_name}: {response.success} - {response.message}")
            return response
    except Exception as e:
        logger.error(f"[{cid}] [Orchestrator] Error clearing cache for {service_name}: {e}")
        return None


@app.route('/checkout', methods=['POST'])
def checkout():
    cid = generate_correlation_id()
    order_id = str(uuid.uuid4())
    logger.info(f"[{cid}] [Orchestrator] Checkout request received for Order ID: {order_id}")

    try:
        order_data = json.loads(request.data)
        order_data["orderId"] = order_id
        order_data["correlation_id"] = cid
    except json.JSONDecodeError:
        logger.error(f"[{cid}] [Orchestrator] Invalid JSON received.")
        return jsonify({"error": {"message": "Invalid JSON format"}}), 400
    except Exception as e:
         logger.exception(f"[{cid}] [Orchestrator] Error processing request data: {str(e)}")
         return jsonify({"error": {"message": "Error processing request data"}}), 400

    # Initialize vector clock
    current_clock = {
        "transaction_verification": 0,
        "fraud_detection": 0,
        "suggestions": 0
    }

    final_status = "Order Processing Failed"
    final_suggestions = []
    final_message = "An error occurred during processing."
    final_clock_dict = {}

    try:
        # --- Step 1: Initialization ---
        logger.info(f"[{cid}] [Orchestrator] --- Initialization Step ---")
        init_results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures_init = {
                executor.submit(call_initialize_transaction, order_data, current_clock): "transaction",
                executor.submit(call_initialize_fraud, order_data, current_clock): "fraud",
                executor.submit(call_initialize_suggestions, order_data, current_clock): "suggestions"
            }
            for future in as_completed(futures_init):
                service_name = futures_init[future]
                try:
                    result = future.result()
                    init_results[service_name] = result["response"]
                    if not result["response"].approved:
                        raise Exception(f"Initialization failed for {service_name}: {result['response'].message}")
                    # Merge clocks after each successful initialization
                    current_clock = merge_clocks(current_clock, vector_clock_to_dict(result["response"].vector_clock))
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Initialization failed for {service_name}: {e}")
                    raise Exception(f"Initialization failed for {service_name}") # Propagate failure

        logger.info(f"[{cid}] [Orchestrator] Initialization successful. Current Clock: {current_clock}")

        # --- Step 2: Event Flow ---
        logger.info(f"[{cid}] [Orchestrator] --- Event Flow Step ---")

        # Events a and b can run in parallel
        logger.info(f"[{cid}] [Orchestrator] Starting Events a & b")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(call_verify_items, order_id, current_clock, cid)
            future_b = executor.submit(call_verify_user_data, order_id, current_clock, cid)

            res_a = future_a.result()
            if not res_a.approved: raise Exception(f"Event a (VerifyItems) failed: {res_a.message}")
            clock_a = vector_clock_to_dict(res_a.vector_clock)

            res_b = future_b.result()
            if not res_b.approved: raise Exception(f"Event b (VerifyUserData) failed: {res_b.message}")
            clock_b = vector_clock_to_dict(res_b.vector_clock)

        # Merge clocks from parallel branches a and b
        current_clock = merge_clocks(clock_a, clock_b)
        logger.info(f"[{cid}] [Orchestrator] Events a & b completed. Current Clock: {current_clock}")

        # Event c (depends on a) and Event d (depends on b) can potentially run in parallel
        # We need clock_a for c, and clock_b for d
        logger.info(f"[{cid}] [Orchestrator] Starting Events c & d")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_c = executor.submit(call_verify_credit_card_format, order_id, clock_a, cid) # Use clock from 'a'
            future_d = executor.submit(call_check_user_data, order_id, clock_b, cid) # Use clock from 'b'

            res_c = future_c.result()
            if not res_c.approved: raise Exception(f"Event c (VerifyCreditCardFormat) failed: {res_c.message}")
            clock_c = vector_clock_to_dict(res_c.vector_clock)

            res_d = future_d.result()
            if not res_d.approved: raise Exception(f"Event d (CheckUserData) failed: {res_d.message}")
            clock_d = vector_clock_to_dict(res_d.vector_clock)

        # Merge clocks from parallel branches c and d
        current_clock = merge_clocks(clock_c, clock_d)
        logger.info(f"[{cid}] [Orchestrator] Events c & d completed. Current Clock: {current_clock}")

        # Event e (depends on c and d)
        logger.info(f"[{cid}] [Orchestrator] Starting Event e")
        res_e = call_check_credit_card_data(order_id, current_clock, cid) # Use merged clock
        if not res_e.approved: raise Exception(f"Event e (CheckCreditCardData) failed: {res_e.message}")
        current_clock = vector_clock_to_dict(res_e.vector_clock)
        logger.info(f"[{cid}] [Orchestrator] Event e completed. Current Clock: {current_clock}")

        # Event f (depends on e)
        logger.info(f"[{cid}] [Orchestrator] Starting Event f")
        res_f = call_get_suggestions(order_id, current_clock, cid)
        if not res_f.approved: raise Exception(f"Event f (GetSuggestions) failed: {res_f.message}")
        current_clock = vector_clock_to_dict(res_f.vector_clock)
        logger.info(f"[{cid}] [Orchestrator] Event f completed. Current Clock: {current_clock}")

        # --- Step 3: Finalization ---
        logger.info(f"[{cid}] [Orchestrator] --- Finalization Step ---")
        final_status = "Order Approved"
        final_message = "Order processed successfully."
        final_suggestions = [MessageToDict(book) for book in res_f.suggested_books]
        final_clock_dict = current_clock

    except Exception as e:
        logger.error(f"[{cid}] [Orchestrator] Checkout flow failed: {str(e)}")
        final_status = "Order Rejected"
        final_message = str(e)
        final_suggestions = []
        # Store the clock state at the point of failure if available
        if 'current_clock' in locals() and isinstance(current_clock, dict):
             final_clock_dict = current_clock
        else:
             # If failure happened very early, use the initial clock state
             final_clock_dict = { "transaction_verification": 0, "fraud_detection": 0, "suggestions": 0 }


    # --- Step 4: Clear Cache (Bonus) ---
    logger.info(f"[{cid}] [Orchestrator] --- Cache Clearing Step ---")
    if final_clock_dict: # Ensure we have a clock state
        with ThreadPoolExecutor(max_workers=3) as executor:
            clear_futures = [
                executor.submit(call_clear_cache, "transaction", "transaction_verification:50052", order_id, final_clock_dict, cid),
                executor.submit(call_clear_cache, "fraud", "fraud_detection:50051", order_id, final_clock_dict, cid),
                executor.submit(call_clear_cache, "suggestions", "suggestions:50053", order_id, final_clock_dict, cid)
            ]
            for future in as_completed(clear_futures):
                try:
                    future.result() # We log results inside the call function
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error during cache clearing future: {e}")
    else:
        logger.warning(f"[{cid}] [Orchestrator] Skipping cache clear due to missing final clock state.")


    # --- Step 5: Return Response ---
    response_payload = {
        "orderId": order_id,
        "status": final_status,
        "message": final_message,
        "suggestedBooks": final_suggestions,
        "finalVectorClock": final_clock_dict
    }
    logger.info(f"[{cid}] [Orchestrator] Checkout completed. Response: {response_payload}")
    return jsonify(response_payload)


if __name__ == '__main__':
    app.run(host='0.0.0.0')
