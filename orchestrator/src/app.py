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
                request = order_executor_pb2.StatusRequest(correlation_id=cid)
                response = stub.GetExecutorStatus(request, timeout=0.5)
                
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
    """
    Initializes the Transaction Verification service with order data.
    Sends the initial request to cache data and prepare for subsequent events.
    
    Args:
        order_data: Dictionary containing order details
        initial_clock_dict: Initial vector clock state
        
    Returns:
        dict: Contains service name and response object
    """
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    logger.info(f"[{cid}] [Orchestrator] Initializing Transaction Verification for order {order_id}")
    
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        
        # Create request with all necessary order data
        request_pb = transaction_verification_pb2.InitRequest(
            order_id=order_id,
            items=[transaction_verification_pb2.Item(name=item.get('name'), quantity=item.get('quantity')) 
                  for item in order_data.get("items", [])],
            credit_card=transaction_verification_pb2.CreditCardInfo(**order_data.get("creditCard", {})),
            billingAddress=transaction_verification_pb2.Address(**order_data.get("billingAddress", {})),
            termsAndConditionsAccepted=order_data.get("termsAndConditionsAccepted", False),
            user_contact=order_data.get("user", {}).get("contact"),
            user_name=order_data.get("user", {}).get("name"),
            vector_clock=dict_to_vector_clock(initial_clock_dict, transaction_verification_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.InitializeTransaction(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] Transaction Verification Initialized. " 
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return {"service": "transaction", "response": response}

def call_initialize_fraud(order_data, initial_clock_dict):
    """
    Initializes the Fraud Detection service with order data.
    Sends the initial request to cache data and prepare for subsequent events.
    
    Args:
        order_data: Dictionary containing order details
        initial_clock_dict: Initial vector clock state
        
    Returns:
        dict: Contains service name and response object
    """
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    logger.info(f"[{cid}] [Orchestrator] Initializing Fraud Detection for order {order_id}")
    
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        
        # Create request with user and credit card information
        request_pb = fraud_detection_pb2.InitRequest(
            order_id=order_id,
            user_info=fraud_detection_pb2.UserInfo(**order_data.get("user", {})),
            credit_card=fraud_detection_pb2.CreditCardInfo(**order_data.get("creditCard", {})),
            vector_clock=dict_to_vector_clock(initial_clock_dict, fraud_detection_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.InitializeFraudDetection(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] Fraud Detection Initialized. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return {"service": "fraud", "response": response}

def call_initialize_suggestions(order_data, initial_clock_dict):
    """
    Initializes the Suggestions service with order data.
    Sends the initial request to cache data and prepare for subsequent events.
    
    Args:
        order_data: Dictionary containing order details
        initial_clock_dict: Initial vector clock state
        
    Returns:
        dict: Contains service name and response object
    """
    cid = order_data["correlation_id"]
    order_id = order_data["orderId"]
    
    # Extract the book name from the first item or use "random" as fallback
    try:
        book_name = order_data.get("items", [])[0].get("name", "random")
    except Exception:
        book_name = "random"
        
    logger.info(f"[{cid}] [Orchestrator] Initializing Suggestions for order {order_id}")
    
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        
        # Create request with book name for generating suggestions
        request_pb = suggestions_pb2.InitRequest(
            order_id=order_id,
            book_name=book_name,
            vector_clock=dict_to_vector_clock(initial_clock_dict, suggestions_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.InitializeSuggestions(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] Suggestions Initialized. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return {"service": "suggestions", "response": response}

# --- Event Specific Calls ---

def call_verify_items(order_id, current_clock_dict, cid):
    """
    Calls the Transaction Verification service to verify items (Event a).
    Ensures all items have valid names and quantities.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyItems (Event a) for order {order_id}")
    
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        
        # Create request with order ID and current vector clock
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.VerifyItems(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] VerifyItems response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

def call_verify_user_data(order_id, current_clock_dict, cid):
    """
    Calls the Transaction Verification service to verify user data (Event b).
    Ensures user name and contact information are present.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyUserData (Event b) for order {order_id}")
    
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        
        # Create request with order ID and current vector clock
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.VerifyUserData(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] VerifyUserData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

def call_verify_credit_card_format(order_id, current_clock_dict, cid):
    """
    Calls the Transaction Verification service to verify credit card format (Event c).
    This event follows Event a in the causal chain.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state (from Event a)
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling VerifyCreditCardFormat (Event c) for order {order_id}")
    
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        
        # Create request with order ID and current vector clock
        # Note: current_clock_dict here is actually clock_a from the call site in checkout()
        request_pb = transaction_verification_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, transaction_verification_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.VerifyCreditCardFormat(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] VerifyCreditCardFormat response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

def call_check_user_data(order_id, current_clock_dict, cid):
    """
    Calls the Fraud Detection service to verify user data for fraud (Event d).
    This event follows Event b in the causal chain.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state (from Event b)
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling CheckUserData (Event d) for order {order_id}")
    
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        
        # Create request with order ID and current vector clock
        # Note: current_clock_dict here is actually clock_b from the call site in checkout()
        request_pb = fraud_detection_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, fraud_detection_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.CheckUserData(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] CheckUserData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

def call_check_credit_card_data(order_id, current_clock_dict, cid):
    """
    Calls the Fraud Detection service to check credit card for fraud (Event e).
    This event follows Events c and d in the causal chain.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state (merged from c and d)
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling CheckCreditCardData (Event e) for order {order_id}")
    
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        
        # Create request with order ID and current vector clock
        request_pb = fraud_detection_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, fraud_detection_pb2)
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.CheckCreditCardData(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] CheckCreditCardData response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

def call_get_suggestions(order_id, current_clock_dict, cid):
    """
    Calls the Suggestions service to get book recommendations (Event f).
    This event follows Event e in the causal chain.
    
    Args:
        order_id: Unique order identifier
        current_clock_dict: Current vector clock state (from Event e)
        cid: Correlation ID for request tracing
        
    Returns:
        EventResponse: Contains approval status, message, and updated vector clock
    """
    logger.info(f"[{cid}] [Orchestrator] Calling GetSuggestions (Event f) for order {order_id}")
    
    # Note: Book name is assumed to be cached in the Suggestions service
    # during InitializeSuggestions
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        
        # Create request with order ID and current vector clock
        request_pb = suggestions_pb2.EventRequest(
            order_id=order_id,
            vector_clock=dict_to_vector_clock(current_clock_dict, suggestions_pb2)
            # book_name is expected to be retrieved from service cache
        )
        
        # Include correlation ID in metadata for request tracing
        response = stub.GetSuggestions(request_pb, metadata=(("correlation-id", cid),))
        
    logger.info(f"[{cid}] [Orchestrator] GetSuggestions response. "
                f"Approved: {response.approved}, Clock: {vector_clock_to_dict(response.vector_clock)}")
    
    return response

# --- Cache Clearing Calls (Bonus) ---

def call_clear_cache(service_name, address, order_id, final_clock_dict, cid):
    """
    Calls a service to clear its cache for a completed order.
    Ensures vector clock causality is maintained during cleanup.
    
    Args:
        service_name: Name of the service to clear cache ("transaction", "fraud", "suggestions")
        address: gRPC address of the service
        order_id: Unique order identifier
        final_clock_dict: Final vector clock state at end of processing
        cid: Correlation ID for request tracing
        
    Returns:
        ClearCacheResponse or None: Response from service or None if error
    """
    logger.info(f"[{cid}] [Orchestrator] Calling Clear Cache for {service_name} for order {order_id}")
    
    try:
        with grpc.insecure_channel(address) as channel:
            # Different services have different RPC method names for cache clearing
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
    """
    Main API endpoint for processing checkout requests.
    Orchestrates the entire event flow for transaction verification,
    fraud detection, suggestions, and order queueing.
    
    Returns:
        tuple: (JSON response, HTTP status code)
    """
    # Generate correlation ID and order ID for request tracking
    cid = generate_correlation_id()
    order_id = str(uuid.uuid4())
    
    logger.info(f"[{cid}] [Orchestrator] Received checkout request")
    
    try:
        # Parse the order data from the request
        order_data = json.loads(request.data)
        order_data["orderId"] = order_id
        order_data["correlation_id"] = cid
        
        if not order_data:
            logger.error(f"[{cid}] [Orchestrator] No order data provided")
            return jsonify({"status": "Order Rejected", "message": "No order data provided"}), 400
            
        logger.info(f"[{cid}] [Orchestrator] Processing order {order_id}")
        
        # --- Step 1: Initialize vector clock ---
        # Start with orchestrator's own clock
        current_clock = {"orchestrator": 0}
        current_clock["orchestrator"] += 1  # Increment own clock
        
        logger.info(f"[{cid}] [Orchestrator] Vector clock initialized: {current_clock}")
        
        # --- Step 2: Initialize Services (Caching Phase) ---
        # Initialize all services with the order data in parallel
        logger.info(f"[{cid}] [Orchestrator] --- Initialization Step ---")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit initialization tasks to thread pool
            futures_init = {
                executor.submit(call_initialize_transaction, order_data, current_clock): "transaction",
                executor.submit(call_initialize_fraud, order_data, current_clock): "fraud",
                executor.submit(call_initialize_suggestions, order_data, current_clock): "suggestions"
            }
            
            # Process results as they complete
            for future in as_completed(futures_init):
                service = futures_init[future]
                try:
                    result = future.result()
                    if result:
                        response_obj = result.get("response")
                        if response_obj and hasattr(response_obj, "vector_clock"):
                            # Convert protobuf vector clock to dictionary
                            response_clock = vector_clock_to_dict(response_obj.vector_clock)
                            # Merge with current clock to maintain causality
                            current_clock = merge_clocks(current_clock, response_clock)
                            logger.info(f"[{cid}] [Orchestrator] Updated vector clock from {service}: {current_clock}")
                
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in initialization for {service}: {e}")
                    return jsonify({
                        "status": "Order Rejected", 
                        "message": f"Service initialization error: {str(e)}"
                    }), 500
        
        logger.info(f"[{cid}] [Orchestrator] All services initialized with vector clock: {current_clock}")
        
        # --- Step 3: Execute Event Flow ---
        # Follow the event dependency graph (DAG) with vector clocks for causality
        logger.info(f"[{cid}] [Orchestrator] --- Event Flow Execution ---")
        
        # Track order status
        final_status = "Order Approved"
        final_message = "Your order has been approved."
        final_suggestions = []
        final_clock_dict = current_clock.copy()
        
        # Event a and b: Verify items and user data (in parallel)
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(call_verify_items, order_id, current_clock, cid)
            future_b = executor.submit(call_verify_user_data, order_id, current_clock, cid)
            
            # Wait for results and update vector clock
            result_a = None
            result_b = None
            
            # Process Event a results
            try:
                result_a = future_a.result()
                if not result_a.approved:  # Check success status
                    final_status = "Order Rejected"
                    final_message = f"Item verification failed: {result_a.message}"
                # Update clock for Event a
                clock_a = vector_clock_to_dict(result_a.vector_clock)
                clock_a = merge_clocks(current_clock, clock_a)
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in verify_items: {e}")
                final_status = "Order Rejected"
                final_message = "Error during item verification"
                
            # Process Event b results
            try:
                result_b = future_b.result()
                if not result_b.approved:
                    final_status = "Order Rejected"
                    final_message = f"User data verification failed: {result_b.message}"
                # Update clock for Event b
                clock_b = vector_clock_to_dict(result_b.vector_clock)
                clock_b = merge_clocks(current_clock, clock_b)
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in verify_user_data: {e}")
                final_status = "Order Rejected"
                final_message = "Error during user data verification"
                
        # Merge clocks from parallel branches a and b
        current_clock = merge_clocks(clock_a, clock_b)
        logger.info(f"[{cid}] [Orchestrator] After events a & b, clock: {current_clock}, status: {final_status}")
        
        # If order is still valid, continue with events c and d
        if final_status == "Order Approved":
            with ThreadPoolExecutor(max_workers=2) as executor:
                # Event c: Verify credit card format (follows a)
                future_c = executor.submit(call_verify_credit_card_format, order_id, clock_a, cid)
                
                # Event d: Check user data for fraud (follows b)
                future_d = executor.submit(call_check_user_data, order_id, clock_b, cid)
                
                # Process results
                result_c = None
                result_d = None
                
                # Process Event c results
                try:
                    result_c = future_c.result()
                    if not result_c.approved:  # Check success status
                        final_status = "Order Rejected"
                        final_message = f"Credit card validation failed: {result_c.message}"
                    clock_c = vector_clock_to_dict(result_c.vector_clock)
                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in verify_credit_card_format: {e}")
                    final_status = "Order Rejected"
                    final_message = "Error during credit card validation"
                    
                # Process Event d results
                try:
                    result_d = future_d.result()
                    if not result_d.approved:  # Check success status
                        final_status = "Order Rejected"
                        final_message = f"User data fraud check failed: {result_d.message}"
                    clock_d = vector_clock_to_dict(result_d.vector_clock)

                except Exception as e:
                    logger.error(f"[{cid}] [Orchestrator] Error in check_user_data: {e}")
                    final_status = "Order Rejected"
                    final_message = "Error during user fraud check"
                    
            # Merge clocks from parallel branches c and d
            current_clock = merge_clocks(clock_c, clock_d)                    
            logger.info(f"[{cid}] [Orchestrator] After events c & d, clock: {current_clock}, status: {final_status}")
        
        # If order is still valid, continue with event e
        if final_status == "Order Approved":
            # Event e: Check credit card for fraud (follows c and d)
            try:
                logger.info(f"[{cid}] [Orchestrator] Starting Event e")
                result_e = call_check_credit_card_data(order_id, current_clock, cid)
                if not result_e.approved:  # Check success status
                    final_status = "Order Rejected"
                    final_message = f"Credit card fraud check failed: {result_e.message}"
                # Update clock
                current_clock = vector_clock_to_dict(result_e.vector_clock)
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in check_credit_card_data: {e}")
                final_status = "Order Rejected"
                final_message = "Error during credit card fraud check"
                
            logger.info(f"[{cid}] [Orchestrator] After event e, clock: {current_clock}, status: {final_status}")
        
        # If order is still valid, continue with event f
        if final_status == "Order Approved":
            # Event f: Get book suggestions (follows e)
            try:
                result_f = call_get_suggestions(order_id, current_clock, cid)
                # Extract book suggestions from response
                final_suggestions = [MessageToDict(book) for book in result_f.suggested_books]
                # Update clock
                current_clock = vector_clock_to_dict(result_f.vector_clock)
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error in get_suggestions: {e}")
                # Don't reject the order if suggestions fail, just log the error
                logger.info(f"[{cid}] [Orchestrator] Could not retrieve suggestions, continuing with order")
                
            logger.info(f"[{cid}] [Orchestrator] After event f, clock: {current_clock}, status: {final_status}")
        
        # Update final vector clock
        final_clock_dict = current_clock.copy()
        
        # --- Step 4: Enqueue order if approved ---
        if final_status == "Order Approved":
            # Check if executor system is healthy (has active leader)
            executor_healthy, leader_id = check_executor_system_health(cid)
            
            if not executor_healthy:
                logger.warning(f"[{cid}] [Orchestrator] Order processing system unavailable. "
                              f"Will still enqueue order but processing may be delayed.")
            else:
                logger.info(f"[{cid}] [Orchestrator] Order processing system is available with leader {leader_id}")
            
            # Enqueue order for processing
            logger.info(f"[{cid}] [Orchestrator] Order approved, enqueueing for processing")
            
            try:
                with grpc.insecure_channel("order_queue:50054", options=[
                    ('grpc.enable_http_proxy', 0),
                    ('grpc.dns_resolver_query_timeout_ms', 1000),
                    ('grpc.use_local_subchannel_pool', 1),
                    ('grpc.dns_resolver_address_sorting_policy', 'ipv4_first')
                ]) as channel:
                    stub = order_queue_pb2_grpc.OrderQueueServiceStub(channel)
                    
                    # Prepare order data for the queue
                    # Convert dictionary items to protocol buffer messages
                    items_pb = []
                    for item in order_data.get("items", []):
                        item_pb = order_queue_pb2.Item(
                            name=item.get("name", ""),
                            quantity=item.get("quantity", 0)
                        )
                        items_pb.append(item_pb)
                    
                    # Create credit card info protocol buffer
                    credit_card_pb = order_queue_pb2.CreditCardInfo(
                        number=order_data.get("credit_card", {}).get("number", ""),
                        expirationDate=order_data.get("credit_card", {}).get("expirationDate", ""),
                        cvv=order_data.get("credit_card", {}).get("cvv", "")
                    )
                    
                    # Create address protocol buffer
                    address_pb = order_queue_pb2.Address(
                        street=order_data.get("billing_address", {}).get("street", ""),
                        city=order_data.get("billing_address", {}).get("city", ""),
                        state=order_data.get("billing_address", {}).get("state", ""),
                        zip=order_data.get("billing_address", {}).get("zip", ""),
                        country=order_data.get("billing_address", {}).get("country", "")
                    )
                    
                    # Create complete order data protocol buffer
                    order_data_pb = order_queue_pb2.OrderData(
                        items=items_pb,
                        user_name=order_data.get("user_name", ""),
                        user_contact=order_data.get("user_contact", ""),
                        credit_card=credit_card_pb,
                        billing_address=address_pb,
                        shipping_method=order_data.get("shipping_method", "standard"),
                        gift_wrapping=order_data.get("gift_wrapping", False),
                        terms_and_conditions_accepted=order_data.get("terms_and_conditions_accepted", False),
                        user_comment=order_data.get("user_comment", "")
                    )
                    
                    # Create enqueue request
                    enqueue_request = order_queue_pb2.EnqueueRequest(
                        order_id=order_id,
                        order_data=order_data_pb
                    )
                    
                    # Add vector clock to request
                    for service, time in final_clock_dict.items():
                        enqueue_request.vector_clock[service] = time
                    
                    # Send request to queue service
                    response = stub.EnqueueOrder(enqueue_request, metadata=(("correlation-id", cid),))
                    
                    if not response.success:
                        logger.error(f"[{cid}] [Orchestrator] Failed to enqueue order: {response.message}")
                        # Don't change order status, just note there was an issue queueing
                    else:
                        logger.info(f"[{cid}] [Orchestrator] Order successfully enqueued for processing")
                        
                        # Add processing info to response message
                        final_message += " Order has been queued for processing."
                        if executor_healthy:
                            final_message += f" Processing will be handled by executor {leader_id}."
            except Exception as e:
                logger.error(f"[{cid}] [Orchestrator] Error enqueueing order: {e}")
                # Don't change order status, just note there was an issue queueing
        
        # --- Step 5: Clear Cache (Bonus) ---
        # Clean up cached data in all services after order processing is complete
        logger.info(f"[{cid}] [Orchestrator] --- Cache Clearing Step ---")
        
        if final_clock_dict:  # Ensure we have a clock state
            with ThreadPoolExecutor(max_workers=3) as executor:
                # Submit cache clearing tasks to thread pool
                clear_futures = [
                    executor.submit(call_clear_cache, "transaction", "transaction_verification:50052", 
                                   order_id, final_clock_dict, cid),
                    executor.submit(call_clear_cache, "fraud", "fraud_detection:50051", 
                                   order_id, final_clock_dict, cid),
                    executor.submit(call_clear_cache, "suggestions", "suggestions:50053", 
                                   order_id, final_clock_dict, cid)
                ]
                
                # Process results as they complete (already logged inside the call function)
                for future in as_completed(clear_futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"[{cid}] [Orchestrator] Error during cache clearing future: {e}")
        
        # --- Step 6: Build and return response ---
        logger.info(f"[{cid}] [Orchestrator] Order processing complete with status {final_status}")
        
        # Prepare final response payload
        response_payload = {
            "orderId": order_id,
            "status": final_status,
            "message": final_message,
            "suggestedBooks": final_suggestions,
            "finalVectorClock": final_clock_dict
        }
        
        return jsonify(response_payload), 200
        
    except Exception as e:
        logger.error(f"[{cid}] [Orchestrator] Unexpected error processing order: {e}")
        return jsonify({
            "status": "Order Rejected",
            "message": f"Server error: {str(e)}"
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0')