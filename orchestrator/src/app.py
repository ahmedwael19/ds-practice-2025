"""
Orchestrator Service (Event-Driven with Vector Clocks)

This module implements an API gateway using Flask to orchestrate multiple gRPC services
following a defined event order using vector clocks.
It integrates with:
    - Transaction Verification Service
    - Fraud Detection Service
    - Book Suggestions Service
    - Order Queue Service
    - Order Executor Service
    - (Indirectly via Order Executor) Books Database Service & Payment Service

The service receives checkout requests, initializes the process across services,
executes events based on a partial order, manages vector clocks, handles failures,
and returns the final status and suggestions.

Author: Ahmed Soliman, Buraq Khan
Date: 2025-04-10
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
# Imports all the necessary protocol buffer modules for service communication
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

order_executor_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/order_executor'))
sys.path.insert(0, order_executor_grpc_path)
import order_executor_pb2, order_executor_pb2_grpc

order_queue_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/order_queue'))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2, order_queue_pb2_grpc

# NEW: Add books_database imports for the test endpoint
books_database_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/books_database'))
sys.path.insert(0, books_database_grpc_path)
import books_database_pb2
import books_database_pb2_grpc


# Configure logging with standardized format for consistent log analysis
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("orchestrator")

# --- Helper Functions ---

def check_executor_system_health(cid):
    """
    Check if the order executor cluster has an active leader.
    Attempts to connect to each executor in the cluster to find the leader.
    
    Args:
        cid: Correlation ID for request tracing
        
    Returns:
        tuple: (healthy_status, leader_id) where:
            - healthy_status is a boolean indicating if the system has a leader
            - leader_id is the ID of the current leader or None if no leader
    """
    executor_addresses = [
        "order_executor_1:50055",
        "order_executor_2:50055",
        "order_executor_3:50055"
    ]
    
    for address in executor_addresses:
        try:
            with grpc.insecure_channel(address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                request_pb = order_executor_pb2.StatusRequest(correlation_id=cid) # Use request_pb consistently
                response = stub.GetExecutorStatus(request_pb, timeout=0.5)
                
                if response.state == "leader" or response.leader_id:
                    logger.info(f"[{cid}] [Orchestrator] Executor system is healthy. Leader: {response.leader_id or response.executor_id}")
                    return True, response.leader_id or response.executor_id
        except Exception as e:
            logger.debug(f"[{cid}] [Orchestrator] Failed to get status from executor {address}: {e}")
            continue
    
    logger.warning(f"[{cid}] [Orchestrator] No active leader found in the executor system")
    return False, None
    
def dict_to_vector_clock(clock_dict, pb_module):
    """
    Convert a Python dictionary vector clock to protobuf format.
    
    Args:
        clock_dict: Dictionary mapping service names to logical timestamps
        pb_module: The protocol buffer module containing the VectorClock message type
        
    Returns:
        VectorClock: Protobuf message with clock data
    """
    vector_clock = pb_module.VectorClock()
    for key, value in clock_dict.items():
        # Ensure key is string, value is int
        vector_clock.clock[str(key)] = int(value)
    return vector_clock

def vector_clock_to_dict(vector_clock):
    """
    Convert a protobuf vector clock to Python dictionary format.
    
    Args:
        vector_clock: Protobuf VectorClock message
        
    Returns:
        dict: Dictionary mapping service names to logical timestamps
    """
    # Always return integers as values
    return {k: int(v) for k, v in vector_clock.clock.items()}

def merge_clocks(clock1, clock2):
    """
    Merge two vector clocks by taking the maximum value for each component.
    Ensures proper type conversion to handle mixed string/integer values.
    
    Args:
        clock1: First vector clock dictionary
        clock2: Second vector clock dictionary
        
    Returns:
        dict: Merged vector clock dictionary
    """
    merged = {}
    all_keys = set(clock1.keys()).union(set(clock2.keys()))
    
    for key in all_keys:
        # Get values with defaults, ensuring both are integers
        val1 = int(clock1.get(key, 0)) if clock1.get(key, 0) is not None else 0
        val2 = int(clock2.get(key, 0)) if clock2.get(key, 0) is not None else 0
        merged[key] = max(val1, val2)
    
    return merged

# Initialize Flask app and enable CORS for cross-origin requests
app = Flask(__name__)
CORS(app, resources={r'/*': {'origins': '*'}})

def generate_correlation_id():
    """
    Generates a unique correlation ID for request tracking in logs.
    Format: timestamp-random4digits
    
    Returns:
        str: Unique correlation ID
    """
    return f"{time.strftime('%Y%m%d%H%M%S')}-{randrange(1000, 9999)}"

# --- gRPC Call Functions for Service Initialization ---

def call_initialize_transaction(order_data, initial_clock_dict):
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    logger.info(f"[{cid}] [Orchestrator] Initializing Transaction Verification for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.InitRequest(
            order_id=order_id,
            items=[transaction_verification_pb2.Item(name=item.get('name'), quantity=item.get('quantity')) 
                  for item in order_data.get("items", [])],
            credit_card=transaction_verification_pb2.CreditCardInfo(**order_data.get("creditCard", {})),
            billingAddress=transaction_verification_pb2.Address(**order_data.get("billingAddress", {})),
            termsAndConditionsAccepted=order_data.get("termsAndConditionsAccepted", False), # Corrected field name
            user_contact=order_data.get("user", {}).get("contact"),
            user_name=order_data.get("user", {}).get("name"),
            vector_clock=dict_to_vector_clock(initial_clock_dict, transaction_verification_pb2)
        )
        response = stub.InitializeTransaction(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] Transaction Verification Initialized. " 
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
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
    logger.info(f"[{cid}] [Orchestrator] Fraud Detection Initialized. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return {"service": "fraud", "response": response}

def call_initialize_suggestions(order_data, initial_clock_dict):
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    try:
        book_name = order_data.get("items", [])[0].get("name", "random book") # More descriptive fallback
    except IndexError: # Handle empty items list
        book_name = "general fiction"
        logger.warning(f"[{cid}] [Orchestrator] No items in order {order_id} for suggestions, using default '{book_name}'.")
    logger.info(f"[{cid}] [Orchestrator] Initializing Suggestions for order {order_id} with book '{book_name}'")
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        request_pb = suggestions_pb2.InitRequest(
            order_id=order_id,
            book_name=book_name,
            vector_clock=dict_to_vector_clock(initial_clock_dict, suggestions_pb2)
        )
        response = stub.InitializeSuggestions(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] Suggestions Initialized. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return {"service": "suggestions", "response": response}

# --- Event Specific Calls ---
# (call_verify_items, call_verify_user_data, ..., call_get_suggestions remain the same)
def call_verify_items(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyItems (Event a) for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        response = stub.VerifyItems(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] VerifyItems response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
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
    logger.info(f"[{cid}] [Orchestrator] VerifyUserData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_verify_credit_card_format(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyCreditCardFormat (Event c) for order {order_id}")
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        response = stub.VerifyCreditCardFormat(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] VerifyCreditCardFormat response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_check_user_data(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling CheckUserData (Event d) for order {order_id}")
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        request_pb = fraud_detection_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, fraud_detection_pb2)
        )
        response = stub.CheckUserData(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] CheckUserData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
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
    logger.info(f"[{cid}] [Orchestrator] CheckCreditCardData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response

def call_get_suggestions(order_id, current_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling GetSuggestions (Event f) for order {order_id}")
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        request_pb = suggestions_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, suggestions_pb2)
        )
        response = stub.GetSuggestions(request_pb, metadata=(("correlation-id", cid),))
    logger.info(f"[{cid}] [Orchestrator] GetSuggestions response. "
                f"Approved: {response.approved}, Suggestions: {len(response.suggested_books)}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    return response
# --- Cache Clearing Calls (Bonus) ---
# (call_clear_cache remains the same)
def call_clear_cache(service_name, address, order_id, final_clock_dict, cid):
    logger.info(f"[{cid}] [Orchestrator] Calling Clear Cache for {service_name} for order {order_id}")
    try:
        with grpc.insecure_channel(address) as channel:
            if service_name == "transaction":
                stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
                request_pb = transaction_verification_pb2.ClearCacheRequest(
                    order_id=order_id, 
                    final_vector_clock=dict_to_vector_clock(final_clock_dict, transaction_verification_pb2)
                )
                response = stub.ClearTransactionCache(request_pb, metadata=(("correlation-id", cid),))
            elif service_name == "fraud":
                stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
                request_pb = fraud_detection_pb2.ClearCacheRequest(
                    order_id=order_id, 
                    final_vector_clock=dict_to_vector_clock(final_clock_dict, fraud_detection_pb2)
                )
                response = stub.ClearFraudCache(request_pb, metadata=(("correlation-id", cid),))
            elif service_name == "suggestions":
                stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
                request_pb = suggestions_pb2.ClearCacheRequest(
                    order_id=order_id, 
                    final_vector_clock=dict_to_vector_clock(final_clock_dict, suggestions_pb2)
                )
                response = stub.ClearSuggestionsCache(request_pb, metadata=(("correlation-id", cid),))
            else:
                logger.error(f"[{cid}] [Orchestrator] Unknown service name for clear cache: {service_name}")
                return None
            logger.info(f"[{cid}] [Orchestrator] Clear Cache response from {service_name}: "
                       f"{response.success} - {response.message}")
            return response
    except Exception as e:
        logger.error(f"[{cid}] [Orchestrator] Error clearing cache for {service_name}: {e}")
        return None

@app.route('/checkout', methods=['POST'])
def checkout():
    cid = generate_correlation_id()
    order_id = str(uuid.uuid4())
    logger.info(f"[{cid}] [Orchestrator] Received checkout request")
    try:
        order_data = json.loads(request.data)
        # Log received items for easier debugging
        logger.info(f"[{cid}] [Orchestrator] Request Items Data: {order_data.get('items')}")

        order_data["orderId"] = order_id
        order_data["correlation_id"] = cid
        
        if not order_data:
            logger.error(f"[{cid}] [Orchestrator] No order data provided")
            return jsonify({"status": "Order Rejected", "message": "No order data provided"}), 400
            
        logger.info(f"[{cid}] [Orchestrator] Processing order {order_id}")
        
        current_clock = {"orchestrator": 1} # Initialized and incremented
        logger.info(f"[{cid}] [Orchestrator] Vector clock initialized: {current_clock}")
        
        logger.info(f"[{cid}] [Orchestrator] --- Initialization Step ---")
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures_init = {
                executor.submit(call_initialize_transaction, order_data, current_clock): "transaction",
                executor.submit(call_initialize_fraud, order_data, current_clock): "fraud",
                executor.submit(call_initialize_suggestions, order_data, current_clock): "suggestions"
            }
            for future in as_completed(futures_init):
                service = futures_init[future]
                try:
                    result = future.result()
                    if result and result.get("response") and hasattr(result["response"], "vector_clock"):
                        response_clock = vector_clock_to_dict(result["response"].vector_clock)
                        current_clock = merge_clocks(current_clock, response_clock)
                        logger.info(f"[{cid}] [Orchestrator] Updated vector clock from {service} init: {current_clock}")
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in initialization for {service}: {e}", exc_info=True)
                    # It's important to decide if an init failure for one service aborts the whole thing.
                    # For now, let's assume it does for simplicity of demo.
                    return jsonify({"status": "Order Rejected", "message": f"Service {service} initialization error: {str(e)}"}), 500
        
        logger.info(f"[{cid}] [Orchestrator] All services initialized. Current vector clock: {current_clock}")
        
        final_status = "Order Approved"
        final_message = "Your order has been approved."
        final_suggestions = []
        
        logger.info(f"[{cid}] [Orchestrator] --- Event Flow Execution ---")
        # Event a and b
        clock_a, clock_b = current_clock.copy(), current_clock.copy() # Start from merged init clock for parallel branches
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(call_verify_items, order_id, clock_a, cid)
            future_b = executor.submit(call_verify_user_data, order_id, clock_b, cid)
            try:
                result_a = future_a.result()
                if not result_a.approved:
                    final_status, final_message = "Order Rejected", f"Item verification failed: {result_a.message}"
                clock_a = merge_clocks(clock_a, vector_clock_to_dict(result_a.vector_clock))
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in verify_items (Event a): {e}", exc_info=True)
                final_status, final_message = "Order Rejected", "Error during item verification"
            
            try:
                result_b = future_b.result()
                if final_status == "Order Approved" and not result_b.approved: # Only update if not already rejected
                    final_status, final_message = "Order Rejected", f"User data verification failed: {result_b.message}"
                clock_b = merge_clocks(clock_b, vector_clock_to_dict(result_b.vector_clock))
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in verify_user_data (Event b): {e}", exc_info=True)
                if final_status == "Order Approved":
                    final_status, final_message = "Order Rejected", "Error during user data verification"

        current_clock = merge_clocks(clock_a, clock_b) # Merge branches from a and b
        logger.info(f"[{cid}] [Orchestrator] After events a & b, clock: {current_clock}, status: {final_status}")

        # Events c and d
        if final_status == "Order Approved":
            clock_c, clock_d = clock_a.copy(), clock_b.copy() # c depends on a's clock, d on b's clock
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_c = executor.submit(call_verify_credit_card_format, order_id, clock_c, cid)
                future_d = executor.submit(call_check_user_data, order_id, clock_d, cid)
                try:
                    result_c = future_c.result()
                    if not result_c.approved:
                        final_status, final_message = "Order Rejected", f"Credit card validation failed: {result_c.message}"
                    clock_c = merge_clocks(clock_c, vector_clock_to_dict(result_c.vector_clock))
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in verify_credit_card_format (Event c): {e}", exc_info=True)
                    final_status, final_message = "Order Rejected", "Error during credit card validation"

                try:
                    result_d = future_d.result()
                    if final_status == "Order Approved" and not result_d.approved:
                        final_status, final_message = "Order Rejected", f"User data fraud check failed: {result_d.message}"
                    clock_d = merge_clocks(clock_d, vector_clock_to_dict(result_d.vector_clock))
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in check_user_data (Event d): {e}", exc_info=True)
                    if final_status == "Order Approved":
                        final_status, final_message = "Order Rejected", "Error during user fraud check"
            current_clock = merge_clocks(current_clock, merge_clocks(clock_c, clock_d)) # Merge with main, then merge c and d
            logger.info(f"[{cid}] [Orchestrator] After events c & d, clock: {current_clock}, status: {final_status}")

        # Event e
        if final_status == "Order Approved":
            try:
                logger.info(f"[{cid}] [Orchestrator] Starting Event e with clock: {current_clock}")
                result_e = call_check_credit_card_data(order_id, current_clock, cid)
                if not result_e.approved:
                    final_status, final_message = "Order Rejected", f"Credit card fraud check failed: {result_e.message}"
                current_clock = merge_clocks(current_clock, vector_clock_to_dict(result_e.vector_clock))
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in check_credit_card_data (Event e): {e}", exc_info=True)
                final_status, final_message = "Order Rejected", "Error during credit card fraud check"
            logger.info(f"[{cid}] [Orchestrator] After event e, clock: {current_clock}, status: {final_status}")
        
        # Event f
        if final_status == "Order Approved":
            try:
                logger.info(f"[{cid}] [Orchestrator] Starting Event f with clock: {current_clock}")
                result_f = call_get_suggestions(order_id, current_clock, cid)
                final_suggestions = [MessageToDict(book) for book in result_f.suggested_books]
                current_clock = merge_clocks(current_clock, vector_clock_to_dict(result_f.vector_clock))
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in get_suggestions (Event f): {e}", exc_info=True)
                logger.info(f"[{cid}] [Orchestrator] Could not retrieve suggestions, but continuing with order approval if otherwise valid.")
            logger.info(f"[{cid}] [Orchestrator] After event f, clock: {current_clock}, status: {final_status}")
        
        final_clock_dict = current_clock.copy()
        
        if final_status == "Order Approved":
            executor_healthy, leader_id = check_executor_system_health(cid)
            if not executor_healthy:
                logger.warning(f"[{cid}] [Orchestrator] Order processing system unavailable. Will still enqueue order; processing may be delayed.")
            else:
                logger.info(f"[{cid}] [Orchestrator] Order processing system available with leader {leader_id}")
            
            logger.info(f"[{cid}] [Orchestrator] Order approved, enqueueing for processing.")
            try:
                with grpc.insecure_channel("order_queue:50054") as channel: # Removed problematic gRPC options
                    stub = order_queue_pb2_grpc.OrderQueueServiceStub(channel)
                    items_pb = []
                    for item_json in order_data.get("items", []): # Iterate over items from parsed JSON
                        # IMPORTANT: Ensure item_json has 'name' and 'quantity'
                        # If your frontend sends book_id and price, you should pass them here too
                        # after updating order_queue.proto Item message.
                        item_pb = order_queue_pb2.Item(
                            name=item_json.get("name", ""), 
                            quantity=item_json.get("quantity", 0)
                            # book_id=item_json.get("book_id", "") # If you add book_id to proto
                            # price=item_json.get("price", 0.0) # If you add price to proto
                        )
                        items_pb.append(item_pb)
                    
                    credit_card_info = order_data.get("creditCard", {}) # Renamed for clarity
                    credit_card_pb = order_queue_pb2.CreditCardInfo(
                        number=credit_card_info.get("number", ""),
                        expirationDate=credit_card_info.get("expirationDate", ""),
                        cvv=credit_card_info.get("cvv", "")
                    )
                    
                    billing_address_info = order_data.get("billingAddress", {}) # Renamed
                    address_pb = order_queue_pb2.Address( # Assuming field names match proto
                        street=billing_address_info.get("street", ""),
                        city=billing_address_info.get("city", ""),
                        state=billing_address_info.get("state", ""),
                        zip=billing_address_info.get("zip", ""),
                        country=billing_address_info.get("country", "")
                    )
                    user_info = order_data.get("user", {})
                    order_data_pb_for_queue = order_queue_pb2.OrderData( # Renamed
                        items=items_pb,
                        user_name=user_info.get("name", ""), # Corrected user_name source
                        user_contact=user_info.get("contact", ""), # Corrected user_contact source
                        credit_card=credit_card_pb,
                        billing_address=address_pb, # Corrected billing_address source
                        shipping_method=order_data.get("shippingMethod", "standard"), # Corrected
                        gift_wrapping=order_data.get("giftWrapping", False), # Corrected
                        terms_and_conditions_accepted=order_data.get("termsAccepted", False), # Corrected (from termsAccepted in JS)
                        user_comment=order_data.get("userComment", "") # Corrected
                        # total_amount= calculated_total_amount # If you calculate and add to OrderData proto
                    )
                    enqueue_request = order_queue_pb2.EnqueueRequest(
                        order_id=order_id,
                        order_data=order_data_pb_for_queue # Use renamed variable
                    )
                    for service, time_val in final_clock_dict.items(): # Use time_val consistently
                        enqueue_request.vector_clock[service] = time_val
                    
                    response = stub.EnqueueOrder(enqueue_request, metadata=(("correlation-id", cid),))
                    if not response.success:
                        logger.error(f"[{cid}] [Orchestrator] Failed to enqueue order: {response.message}")
                    else:
                        logger.info(f"[{cid}] [Orchestrator] Order successfully enqueued for processing.")
                        final_message += " Order has been queued for processing."
                        if executor_healthy:
                            final_message += f" Processing will be handled by executor {leader_id}."
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error enqueueing order: {e}", exc_info=True)
        
        logger.info(f"[{cid}] [Orchestrator] --- Cache Clearing Step ---")
        if final_clock_dict:
            with ThreadPoolExecutor(max_workers=3) as executor:
                clear_futures = [
                    executor.submit(call_clear_cache, "transaction", "transaction_verification:50052", order_id, final_clock_dict, cid),
                    executor.submit(call_clear_cache, "fraud", "fraud_detection:50051", order_id, final_clock_dict, cid),
                    executor.submit(call_clear_cache, "suggestions", "suggestions:50053", order_id, final_clock_dict, cid)
                ]
                for future in as_completed(clear_futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"[{cid}] [Orchestrator] Error during cache clearing future: {e}", exc_info=True)
        
        logger.info(f"[{cid}] [Orchestrator] Order processing complete with status {final_status}")
        response_payload = {
            "orderId": order_id,
            "status": final_status,
            "message": final_message,
            "suggestedBooks": final_suggestions,
            "finalVectorClock": final_clock_dict
        }
        return jsonify(response_payload), 200
        
    except Exception as e:
        logger.error(f"[{cid}] [Orchestrator] Unexpected error processing order: {e}", exc_info=True)
        return jsonify({"status": "Order Rejected", "message": f"Server error: {str(e)}"}), 500

# In orchestrator/app.py

# ... (other imports and Flask app setup)

@app.route('/stock/read', methods=['GET'])
def read_stock_test_endpoint():
    cid = generate_correlation_id()
    logger.info(f"[{cid}] [Orchestrator-Test] Received GET request for /stock/read")

    # CORRECT WAY TO GET PARAMETERS FOR A GET REQUEST: from request.args
    book_id_to_read = request.args.get("book_id")
    logger.info(f"[{cid}] [Orchestrator-Test] book_id from query params: {book_id_to_read}")

    if not book_id_to_read:
        logger.warning(f"[{cid}] [Orchestrator-Test] /stock/read: book_id query param is missing.")
        # Add "success": False to your error responses for consistency if pytest checks it
        return jsonify({"status": "Error", "message": "book_id query param is required", "success": False}), 400

    logger.info(f"[{cid}] [Orchestrator-Test] Attempting to read stock for book_id: '{book_id_to_read}'")

    # --- DB Leader Discovery Logic (Keep your existing, working logic here) ---
    db_node_addresses = os.environ.get("DB_NODE_ADDRESSES", "books_database_1:50060,books_database_2:50061,books_database_3:50062").split(',')
    db_leader_address = None
    # (Your full leader discovery loop as you posted it - it seems correct)
    for addr in db_node_addresses:
        try:
            with grpc.insecure_channel(addr.strip()) as channel_check:
                stub_check = books_database_pb2_grpc.BooksDatabaseServiceStub(channel_check)
                role_resp = stub_check.GetNodeRole(books_database_pb2.GetNodeRoleRequest(), timeout=0.5)
                if role_resp.role == "leader":
                    db_leader_address = addr.strip()
                    logger.info(f"[{cid}] [Orchestrator-Test] Found DB leader at {db_leader_address} for /stock/read")
                    break
                elif role_resp.leader_id and role_resp.leader_id in db_node_addresses :
                    hinted_leader_addr = role_resp.leader_id
                    logger.info(f"[{cid}] [Orchestrator-Test] DB Node {addr} hinted leader is {hinted_leader_addr}. Verifying...")
                    try:
                        with grpc.insecure_channel(hinted_leader_addr) as hinted_channel:
                            hinted_stub = books_database_pb2_grpc.BooksDatabaseServiceStub(hinted_channel)
                            hinted_role_resp = hinted_stub.GetNodeRole(books_database_pb2.GetNodeRoleRequest(), timeout=0.5)
                            if hinted_role_resp.role == "leader":
                                db_leader_address = hinted_leader_addr
                                logger.info(f"[{cid}] [Orchestrator-Test] Confirmed hinted DB leader at {db_leader_address} for /stock/read")
                                break 
                            else: 
                                db_leader_address = None 
                                logger.warning(f"[{cid}] [Orchestrator-Test] Hinted DB leader {hinted_leader_addr} was not the leader. Continuing search.")
                    except Exception as e_hint_verify: # Catch specific exception during verification
                        db_leader_address = None 
                        logger.warning(f"[{cid}] [Orchestrator-Test] Hinted DB leader {hinted_leader_addr} was unreachable during verification: {e_hint_verify}. Continuing search.")
        except Exception as e_discover:
            logger.debug(f"[{cid}] [Orchestrator-Test] Error checking DB node {addr} for leader: {e_discover}")
            continue
    # --- End DB Leader Discovery ---
    
    if not db_leader_address:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/read: Could not find BooksDatabase leader.")
        return jsonify({"status": "Error", "message": "Could not find BooksDatabase leader", "success": False}), 503

    try:
        logger.info(f"[{cid}] [Orchestrator-Test] /stock/read: Calling ReadStock on DB leader {db_leader_address} for book {book_id_to_read}")
        with grpc.insecure_channel(db_leader_address) as channel:
            stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
            # Use the correct variable for the book_id being read
            read_request_pb = books_database_pb2.ReadStockRequest(book_id=book_id_to_read)
            response = stub.ReadStock(read_request_pb, timeout=3.0)

            if response.success:
                logger.info(f"[{cid}] [Orchestrator-Test] /stock/read: ReadStock success for {book_id_to_read}. Quantity: {response.quantity}")
                return jsonify({
                    "status": "Success",  # For consistency if pytest checks this
                    "success": True,      # Pytest checks this boolean
                    "book_id": response.book_id,
                    "quantity": response.quantity
                }), 200
            else:
                logger.warning(f"[{cid}] [Orchestrator-Test] /stock/read: ReadStock call to DB for {book_id_to_read} failed. Message: {response.message}")
                return jsonify({
                    "status": "Failed",
                    "success": False,
                    "message": response.message,
                    "book_id": book_id_to_read
                }), 404 # Or 200 with success:false, but 404 is good for "not found"
    except grpc.RpcError as e_rpc:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/read: gRPC error calling ReadStock for {book_id_to_read}: {e_rpc.code()} - {e_rpc.details()}", exc_info=True)
        return jsonify({"status": "Error", "message": f"gRPC error: {e_rpc.details()}", "success": False}), 500
    except Exception as e_generic:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/read: Unexpected error for {book_id_to_read}: {e_generic}", exc_info=True)
        return jsonify({"status": "Error", "message": str(e_generic), "success": False}), 500


# Your /stock/increment endpoint (which uses request.json) is likely fine as is,
# because pytest's requests.post(..., json=payload) sends the correct Content-Type.
# Just ensure it returns the expected "status": "Success" for pytest.
# I've added the same `success: True/False` to its JSON response for robustness.

@app.route('/stock/increment', methods=['POST'])
def increment_stock_test_endpoint():
    cid = generate_correlation_id()
    logger.info(f"[{cid}] [Orchestrator-Test] Received POST request for /stock/increment")

    if not request.is_json: # Good check
        logger.warning(f"[{cid}] [Orchestrator-Test] /stock/increment: Request Content-Type was not application/json.")
        return jsonify({"status": "Error", "message": "Request must be JSON", "success": False}), 415
    try:
        data = request.get_json()
    except Exception as e_json:
        logger.warning(f"[{cid}] [Orchestrator-Test] /stock/increment: Failed to parse JSON body: {e_json}")
        return jsonify({"status": "Error", "message": "Invalid JSON body", "success": False}), 400

    book_id_to_increment = data.get("book_id")
    amount_to_increment_by = data.get("amount", 1)

    if not book_id_to_increment:
        logger.warning(f"[{cid}] [Orchestrator-Test] /stock/increment: book_id is missing in JSON body.")
        return jsonify({"status": "Error", "message": "book_id is required in JSON body", "success": False}), 400
    if not isinstance(amount_to_increment_by, int) or amount_to_increment_by <= 0:
        logger.warning(f"[{cid}] [Orchestrator-Test] /stock/increment: amount must be a positive integer. Got: {amount_to_increment_by}")
        return jsonify({"status": "Error", "message": "amount must be a positive integer", "success": False}), 400

    logger.info(f"[{cid}] [Orchestrator-Test] Attempting to increment stock for '{book_id_to_increment}' by {amount_to_increment_by}")

    # --- DB Leader Discovery Logic (Keep your existing, working logic here) ---
    db_node_addresses = os.environ.get("DB_NODE_ADDRESSES", "books_database_1:50060,books_database_2:50061,books_database_3:50062").split(',')
    db_leader_address = None
    # (Your full leader discovery loop as you posted it)
    for addr in db_node_addresses:
        try:
            with grpc.insecure_channel(addr.strip()) as channel_check:
                stub_check = books_database_pb2_grpc.BooksDatabaseServiceStub(channel_check)
                role_resp = stub_check.GetNodeRole(books_database_pb2.GetNodeRoleRequest(), timeout=0.5)
                if role_resp.role == "leader":
                    db_leader_address = addr.strip()
                    logger.info(f"[{cid}] [Orchestrator-Test] Found DB leader at {db_leader_address} for /stock/increment")
                    break
                elif role_resp.leader_id and role_resp.leader_id in db_node_addresses :
                    hinted_leader_addr = role_resp.leader_id
                    logger.info(f"[{cid}] [Orchestrator-Test] DB Node {addr} hinted leader is {hinted_leader_addr}. Verifying...")
                    try:
                        with grpc.insecure_channel(hinted_leader_addr) as hinted_channel:
                            hinted_stub = books_database_pb2_grpc.BooksDatabaseServiceStub(hinted_channel)
                            hinted_role_resp = hinted_stub.GetNodeRole(books_database_pb2.GetNodeRoleRequest(), timeout=0.5)
                            if hinted_role_resp.role == "leader":
                                db_leader_address = hinted_leader_addr
                                logger.info(f"[{cid}] [Orchestrator-Test] Confirmed hinted DB leader at {db_leader_address} for /stock/increment")
                                break 
                            else: 
                                db_leader_address = None 
                                logger.warning(f"[{cid}] [Orchestrator-Test] Hinted DB leader {hinted_leader_addr} was not the leader. Continuing search.")
                    except Exception as e_hint_verify_inc:
                        db_leader_address = None 
                        logger.warning(f"[{cid}] [Orchestrator-Test] Hinted DB leader {hinted_leader_addr} was unreachable during verification for increment: {e_hint_verify_inc}. Continuing search.")
        except Exception as e_discover_inc:
            logger.debug(f"[{cid}] [Orchestrator-Test] Error checking DB node {addr} for leader (increment): {e_discover_inc}")
            continue
    # --- End DB Leader Discovery ---

    if not db_leader_address:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/increment: Could not find BooksDatabase leader.")
        return jsonify({"status": "Error", "message": "Could not find BooksDatabase leader", "success": False}), 503

    try:
        logger.info(f"[{cid}] [Orchestrator-Test] /stock/increment: Calling IncrementStock on DB leader {db_leader_address} for {book_id_to_increment}")
        with grpc.insecure_channel(db_leader_address) as channel:
            stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
            increment_request_pb = books_database_pb2.IncrementStockRequest(
                book_id=book_id_to_increment,
                amount_to_increment=amount_to_increment_by
            )
            response = stub.IncrementStock(increment_request_pb, timeout=5.0)
            
            if response.success:
                logger.info(f"[{cid}] [Orchestrator-Test] /stock/increment: Successfully incremented stock for '{book_id_to_increment}'. New quantity: {response.new_quantity}")
                return jsonify({
                    "status": "Success", # Pytest helper checks this
                    "success": True,     # For consistency
                    "message": response.message, 
                    "book_id": response.book_id, 
                    "new_quantity": response.new_quantity
                }), 200
            else:
                logger.warning(f"[{cid}] [Orchestrator-Test] /stock/increment: Failed to increment stock for '{book_id_to_increment}' from DB. Message: {response.message}")
                return jsonify({"status": "Failed", "success": False, "message": response.message}), 400
                
    except grpc.RpcError as e_rpc_inc:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/increment: gRPC error calling IncrementStock for {book_id_to_increment}: {e_rpc_inc.code()} - {e_rpc_inc.details()}", exc_info=True)
        return jsonify({"status": "Error", "message": f"gRPC error: {e_rpc_inc.details()}", "success": False}), 500
    except Exception as e_generic_inc:
        logger.error(f"[{cid}] [Orchestrator-Test] /stock/increment: Unexpected error for {book_id_to_increment}: {e_generic_inc}", exc_info=True)
        return jsonify({"status": "Error", "message": f"Unexpected server error: {str(e_generic_inc)}", "success": False}), 500

# ... (rest of your orchestrator/app.py, including if __name__ == "__main__":)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) # Explicitly setting port to match docker-compose internal