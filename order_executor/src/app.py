import os
import uuid
import time
import random
import grpc
import logging
import threading
from concurrent import futures

# Import generated gRPC code
import sys
# gRPC Protobuf imports
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
order_executor_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/order_executor'))
sys.path.insert(0, order_executor_grpc_path)
order_queue_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/order_queue'))
sys.path.insert(0, order_queue_grpc_path)
payment_service_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/payment_service'))
sys.path.insert(0, payment_service_grpc_path)

# NEW: Add books_database imports
books_database_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/books_database'))
sys.path.insert(0, books_database_grpc_path)

import order_executor_pb2
import order_executor_pb2_grpc
import order_queue_pb2
import order_queue_pb2_grpc
import payment_service_pb2
import payment_service_pb2_grpc
import books_database_pb2
import books_database_pb2_grpc


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("order_executor")

# Get the executor instance ID from environment (set in docker-compose)
EXECUTOR_ID = os.environ.get("EXECUTOR_ID", str(uuid.uuid4())[:8])
QUEUE_SERVICE = os.environ.get("QUEUE_SERVICE", "order_queue:50054")
PAYMENT_SERVICE_ADDRESS = os.environ.get("PAYMENT_SERVICE_ADDRESS", "payment_service:50057")

# Get all peer executor addresses from environment
PEERS_STR = os.environ.get("EXECUTOR_PEERS", "")
PEERS = [p.strip() for p in PEERS_STR.split(",") if p.strip() and p.strip() != f"order_executor_{EXECUTOR_ID}:50055"]

# --- Define Book Prices (as a stand-in until DB has prices) ---
BOOK_PRICES = {
    "book_101_clean_code": 29.99,
    "book_102_pragmatic_programmer": 34.50,
    "book_103_design_patterns": 39.75,
    "book_104_domain_driven_design": 42.00,
}
DEFAULT_BOOK_PRICE = 19.99 # Fallback
# Raft states
FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"

# For DB Raft Leader Discovery (same states)
DB_FOLLOWER, DB_CANDIDATE, DB_LEADER = "follower", "candidate", "leader"

# --- Define Book Prices (as a stand-in until DB has prices) ---
# YOU MUST ENSURE THESE book_id keys match what your mapping produces
BOOK_PRICES = {
    "book_101_clean_code": 29.99,
    "book_102_pragmatic_programmer": 34.50,
    "book_103_design_patterns": 39.75,
    "book_104_domain_driven_design": 42.00,
    # Add any other book_ids and their prices if you test with them
}
DEFAULT_BOOK_PRICE = 19.99 # Fallback if book_id not in our price list

class RaftConsensus:
    def __init__(self, node_id, peers):
        self.node_id = node_id
        self.peers = peers
        self.state = FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.leader_id = None
        self.election_timeout_duration = self._get_random_election_timeout_duration()
        self.last_heartbeat_time = time.time()
        self.votes_received_count = 0
        self.processed_orders_count = 0
        
        self.lock = threading.RLock()
        self.processing_order_flag = False
        
        self.db_node_addresses_str = os.environ.get("DB_NODE_ADDRESSES", "books_database_1:50060,books_database_2:50061,books_database_3:50062")
        self.db_node_addresses = [addr.strip() for addr in self.db_node_addresses_str.split(',') if addr.strip()]
        self.current_db_leader_address = None
        self.db_leader_lock = threading.Lock()

        self.is_running = True
        self.election_timer_thread = threading.Thread(target=self._run_election_timer_loop)
        self.election_timer_thread.daemon = True
        self.election_timer_thread.start()
        
        self.leader_heartbeat_thread = None
        
        logger.info(f"Executor {self.node_id} initialized. OE Peers: {self.peers}. DB Nodes: {self.db_node_addresses}")
        
    def _get_random_election_timeout_duration(self):
        return random.uniform(1.5, 3.0)
        
    def _run_election_timer_loop(self):
        while self.is_running:
            time.sleep(0.1)
            with self.lock:
                if self.state == LEADER:
                    continue
                if time.time() - self.last_heartbeat_time > self.election_timeout_duration:
                    logger.info(f"[{self.node_id}] Election timeout! Last HB: {self.last_heartbeat_time}, Now: {time.time()}. Starting election.")
                    self._initiate_election()
                    
    def _initiate_election(self):
        with self.lock:
            self.state = CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received_count = 1
            self.leader_id = None
            self.election_timeout_duration = self._get_random_election_timeout_duration()
            self.last_heartbeat_time = time.time()
            logger.info(f"[{self.node_id}] Initiating election for term {self.current_term}.")
            for peer_address in self.peers:
                threading.Thread(target=self._send_vote_request_to_peer, args=(peer_address,)).start()
                
    def _send_vote_request_to_peer(self, peer_address):
        correlation_id = str(uuid.uuid4())
        term_at_request_time = -1
        with self.lock:
            if self.state != CANDIDATE:
                return
            term_at_request_time = self.current_term
            request_pb = order_executor_pb2.VoteRequest(
                candidate_id=self.node_id,
                term=term_at_request_time,
                correlation_id=correlation_id
            )
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                logger.debug(f"[{self.node_id}][{correlation_id}] Requesting vote from {peer_address} for term {term_at_request_time}.")
                response_pb = stub.RequestVote(request_pb, timeout=0.5)
                with self.lock:
                    if self.state != CANDIDATE or self.current_term != term_at_request_time:
                        logger.debug(f"[{self.node_id}][{correlation_id}] Vote response from {peer_address} is stale or state changed. Ignoring.")
                        return
                    if response_pb.term > self.current_term:
                        logger.info(f"[{self.node_id}][{correlation_id}] Discovered higher term {response_pb.term} from vote response by {peer_address}. Stepping down.")
                        self._transition_to_follower(response_pb.term)
                        return
                    if response_pb.vote_granted:
                        logger.info(f"[{self.node_id}][{correlation_id}] Vote GRANTED by {peer_address} for term {self.current_term}.")
                        self.votes_received_count += 1
                        if self.votes_received_count > (len(self.peers) + 1) / 2:
                            self._transition_to_leader()
        except Exception as e:
            logger.error(f"[{self.node_id}][{correlation_id}] Error requesting vote from {peer_address}: {e}")

    def _transition_to_follower(self, new_term, new_leader_id=None):
        logger.info(f"[{self.node_id}] Transitioning to FOLLOWER. Old Term: {self.current_term}, New Term: {new_term}. Old State: {self.state}")
        self.state = FOLLOWER
        self.current_term = new_term
        self.voted_for = None
        self.leader_id = new_leader_id
        self.election_timeout_duration = self._get_random_election_timeout_duration()
        self.last_heartbeat_time = time.time()

    def _transition_to_leader(self):
        if self.state != CANDIDATE:
            return
        self.state = LEADER
        self.leader_id = self.node_id
        logger.info(f"Node {self.node_id} PROMOTED TO LEADER for term {self.current_term}.")
        self._discover_db_leader_async()
        if self.leader_heartbeat_thread is None or not self.leader_heartbeat_thread.is_alive():
            self.leader_heartbeat_thread = threading.Thread(target=self._send_heartbeats_as_leader_loop)
            self.leader_heartbeat_thread.daemon = True
            self.leader_heartbeat_thread.start()
        threading.Thread(target=self._process_orders_as_leader_loop, daemon=True).start()
                
    def _send_heartbeats_as_leader_loop(self):
        while self.is_running:
            time.sleep(0.5)
            current_term_for_hb = -1
            with self.lock:
                if self.state != LEADER:
                    logger.info(f"[{self.node_id}] No longer LEADER, stopping heartbeats thread.")
                    return
                current_term_for_hb = self.current_term
            correlation_id = str(uuid.uuid4())
            for peer_address in self.peers:
                threading.Thread(target=self._send_single_heartbeat_to_peer, args=(peer_address, current_term_for_hb, correlation_id)).start()
                    
    def _send_single_heartbeat_to_peer(self, peer_address, term, correlation_id):
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                request_pb = order_executor_pb2.HeartbeatRequest(
                    leader_id=self.node_id,
                    term=term,
                    correlation_id=correlation_id
                )
                response_pb = stub.Heartbeat(request_pb, timeout=0.3)
                with self.lock:
                    if response_pb.term > self.current_term:
                        logger.info(f"[{self.node_id}][{correlation_id}] Discovered higher term {response_pb.term} from HB response by {peer_address}. Stepping down.")
                        self._transition_to_follower(response_pb.term)
        except Exception:
            pass
            
    def _process_orders_as_leader_loop(self):
        logger.info(f"[{self.node_id}] LEADER starting order processing loop.")
        while self.is_running:
            should_process = False
            with self.lock:
                if self.state != LEADER:
                    logger.info(f"[{self.node_id}] No longer LEADER, stopping order processing loop.")
                    return
                if not self.processing_order_flag:
                    self.processing_order_flag = True
                    should_process = True
            if should_process:
                try:
                    self._process_one_order_from_queue()
                except Exception as e:
                    logger.error(f"[{self.node_id}] Unhandled error in _process_one_order_from_queue: {e}", exc_info=True)
                finally:
                    with self.lock:
                        self.processing_order_flag = False
            time.sleep(3)
            
    def _discover_db_leader_async(self):
        threading.Thread(target=self._discover_db_leader, daemon=True).start()

    def _discover_db_leader(self):
        with self.db_leader_lock:
            self.current_db_leader_address = None
        logger.info(f"[{self.node_id}] OE Leader: Discovering BooksDatabase leader from {self.db_node_addresses}")
        discovered_leader_addr = None
        for addr in self.db_node_addresses:
            try:
                with grpc.insecure_channel(addr) as channel:
                    stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                    role_req = books_database_pb2.GetNodeRoleRequest()
                    role_resp = stub.GetNodeRole(role_req, timeout=0.5)
                    if role_resp.role == DB_LEADER:
                        discovered_leader_addr = addr
                        logger.info(f"[{self.node_id}] OE Leader: BooksDatabase leader found at {addr} (DB Term: {role_resp.term})")
                        break
                    elif role_resp.leader_id and role_resp.leader_id != addr:
                        logger.debug(f"[{self.node_id}] OE Leader: DB Node {addr} is {role_resp.role}, hints leader is {role_resp.leader_id}")
            except Exception as e:
                logger.warning(f"[{self.node_id}] OE Leader: Error contacting DB node {addr} for leader discovery: {e}")
        if discovered_leader_addr:
            with self.db_leader_lock:
                self.current_db_leader_address = discovered_leader_addr
        else:
            logger.warning(f"[{self.node_id}] OE Leader: No BooksDatabase leader discovered after checking all nodes.")
        return discovered_leader_addr is not None

    def _get_current_db_leader_address_with_retry(self, allow_rediscovery=True):
        with self.db_leader_lock:
            if self.current_db_leader_address:
                return self.current_db_leader_address
        if allow_rediscovery:
            if self._discover_db_leader():
                with self.db_leader_lock:
                    return self.current_db_leader_address
        return None

    def _call_db_service_rpc(self, rpc_method_name, request_pb, max_retries=3):
        attempt = 0
        last_exception = None
        while attempt < max_retries:
            db_leader_addr = self._get_current_db_leader_address_with_retry(allow_rediscovery=(attempt > 0))
            if not db_leader_addr:
                logger.error(f"[{self.node_id}] DB_CALL_FAIL: No DB leader found for {rpc_method_name}. Attempt {attempt+1}/{max_retries}.")
                attempt += 1
                time.sleep(0.2 * attempt) # exponential backoff
                continue
            logger.info(f"[{self.node_id}] DB_CALL: Attempting {rpc_method_name} on DB leader {db_leader_addr} (Attempt {attempt+1})")
            try:
                with grpc.insecure_channel(db_leader_addr) as channel:
                    stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                    method_to_call = getattr(stub, rpc_method_name)
                    response = method_to_call(request_pb, timeout=3.0) 
                    logger.info(f"[{self.node_id}] DB_CALL_SUCCESS: {rpc_method_name} on {db_leader_addr} successful.")
                    return response
            except grpc.RpcError as e:
                last_exception = e
                logger.warning(f"[{self.node_id}] DB_CALL_RPC_ERROR: {rpc_method_name} on {db_leader_addr} failed: {e.code()} - {e.details()}")
                if e.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL, grpc.StatusCode.DEADLINE_EXCEEDED):
                    with self.db_leader_lock:
                        self.current_db_leader_address = None 
                    logger.info(f"[{self.node_id}] DB_CALL: Cleared current DB leader due to RPC error. Will attempt rediscovery.")
                elif e.code() == grpc.StatusCode.ABORTED and "Not the leader" in e.details():
                     with self.db_leader_lock:
                        self.current_db_leader_address = None
                     logger.info(f"[{self.node_id}] DB_CALL: DB node {db_leader_addr} reported it is not the leader. Retrying discovery.")
                else:
                    logger.error(f"[{self.node_id}] DB_CALL_UNHANDLED_RPC_ERROR: {rpc_method_name} on {db_leader_addr} - {e.code()}: {e.details()}")
            except Exception as ex:
                last_exception = ex
                logger.error(f"[{self.node_id}] DB_CALL_UNEXPECTED_ERROR: Calling {rpc_method_name} on {db_leader_addr}: {ex}", exc_info=True)
                with self.db_leader_lock:
                    self.current_db_leader_address = None
            attempt += 1
            time.sleep(0.3 * attempt) # exponential backoff
        logger.error(f"[{self.node_id}] DB_CALL_FINAL_FAIL: {rpc_method_name} failed after {max_retries} retries. Last error: {last_exception}")
        return None

    def _process_one_order_from_queue(self):
        correlation_id = str(uuid.uuid4())
        logger.info(f"[{self.node_id}][{correlation_id}] OE Leader: Attempting to dequeue an order.")
        
        order_id = None
        order_data_pb = None # Renamed to avoid confusion with internal dicts
        
        # 1. Dequeue Order
        try:
            with grpc.insecure_channel(QUEUE_SERVICE) as channel:
                queue_stub = order_queue_pb2_grpc.OrderQueueServiceStub(channel)
                status_request = order_queue_pb2.QueueStatusRequest(executor_id=self.node_id)
                status_response = queue_stub.GetQueueStatus(status_request, metadata=(("correlation-id", correlation_id),), timeout=1.0)
                
                if not status_response.has_pending_orders:
                    logger.debug(f"[{self.node_id}][{correlation_id}] OE Leader: No orders in queue.")
                    return # Nothing to process
                
                dequeue_request = order_queue_pb2.DequeueRequest(executor_id=self.node_id)
                dequeue_response = queue_stub.DequeueOrder(dequeue_request, metadata=(("correlation-id", correlation_id),), timeout=1.0)
                
                if not dequeue_response.success or not dequeue_response.order_id:
                    logger.info(f"[{self.node_id}][{correlation_id}] OE Leader: Failed to dequeue order or queue empty: {dequeue_response.message}")
                    return
                
                order_id = dequeue_response.order_id
                order_data_pb = dequeue_response.order_data # This is order_queue_pb2.OrderData
        except grpc.RpcError as e:
            logger.error(f"[{self.node_id}][{correlation_id}] OE Leader: RPC error interacting with queue service: {e.code()} - {e.details()}", exc_info=True)
            return
        except Exception as e_gen:
            logger.error(f"[{self.node_id}][{correlation_id}] OE Leader: Unexpected error during queue interaction: {e_gen}", exc_info=True)
            return

        # Ensure order was successfully dequeued
        if not (order_id and order_data_pb):
            logger.error(f"[{self.node_id}][{correlation_id}] OE Leader: Order ID or OrderData is None after dequeue attempt. Aborting processing.")
            return

        transaction_id = str(uuid.uuid4()) # Generate TX_ID once for the whole 2PC
        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Starting 2PC for order {order_id} with {len(order_data_pb.items)} items.")
        logger.debug(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Dequeued OrderData: {str(order_data_pb)[:500]}") # Log more data

        # --- Calculate total order amount ---
        calculated_amount = 0.0
        if not order_data_pb.items:
            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Order {order_id} has no items. Aborting pre-2PC.")
            return

        for item in order_data_pb.items:
            book_id_for_price = None
            item_name_lower = item.name.lower() # item.name comes from order_queue_pb2.Item
            
            # ** CRITICAL MAPPING FOR PRICES **
            # Ensure these names match what's in your BOOK_PRICES keys (which should be book_ids)
            if "clean code" == item_name_lower: book_id_for_price = "book_101_clean_code"
            elif "pragmatic programmer" == item_name_lower: book_id_for_price = "book_102_pragmatic_programmer"
            elif "design patterns" == item_name_lower: book_id_for_price = "book_103_design_patterns"
            elif "domain-driven design" == item_name_lower: book_id_for_price = "book_104_domain_driven_design"
            # Add other mappings if your frontend sends other names that map to your BOOK_PRICES keys

            price = BOOK_PRICES.get(book_id_for_price, DEFAULT_BOOK_PRICE)
            if book_id_for_price is None: # Name didn't map to a known book_id for pricing
                logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: No specific price mapping for item name '{item.name}', using default ${DEFAULT_BOOK_PRICE:.2f}")
            
            calculated_amount += item.quantity * price
        
        if calculated_amount <= 0 and len(order_data_pb.items) > 0 :
             logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Calculated amount is ${calculated_amount:.2f}. Using fallback amount of 1.00 as items exist.")
             calculated_amount = 1.00

        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Calculated total amount for order {order_id} is ${calculated_amount:.2f}")

        # 1. Construct BookOperations for DB Prepare from order_data_pb.items
        db_operations = []
        valid_order_items_for_db = True
        for item in order_data_pb.items:
            book_id_in_db = None
            item_name_lower = item.name.lower() # item.name comes from order_queue_pb2.Item

            # ** CRITICAL MAPPING FOR DATABASE book_id **
            # This MUST map to the exact keys used in books_database/app.py self.datastore
            if "clean code" == item_name_lower: book_id_in_db = "book_101_clean_code"
            elif "pragmatic programmer" == item_name_lower: book_id_in_db = "book_102_pragmatic_programmer"
            elif "design patterns" == item_name_lower: book_id_in_db = "book_103_design_patterns"
            elif "domain-driven design" == item_name_lower: book_id_in_db = "book_104_domain_driven_design"
            # Add other mappings if your frontend sends other names

            if not book_id_in_db:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: CRITICAL - Cannot map item NAME '{item.name}' to a DB book_id. Aborting order processing for this item.")
                valid_order_items_for_db = False
                break
            db_operations.append(books_database_pb2.BookOperation(book_id=book_id_in_db, quantity_change=-item.quantity))
        
        if not valid_order_items_for_db or not db_operations:
            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Order {order_id} has no valid items with book_ids for DB operations. Aborting pre-2PC.")
            return

        # --- 2PC State Variables ---
        payment_vote_status = None 
        db_vote_status = None      
        payment_prepared_successfully = False
        db_prepared_successfully = False

        # --- Prepare Phase ---
        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering PREPARE phase.")
        try:
            with grpc.insecure_channel(PAYMENT_SERVICE_ADDRESS) as payment_channel:
                payment_stub = payment_service_pb2_grpc.PaymentServiceStub(payment_channel)
                ps_prepare_req = payment_service_pb2.PaymentPrepareRequest(
                    transaction_id=transaction_id, order_id=order_id, amount=calculated_amount
                )
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Prepare to PaymentService with amount ${calculated_amount:.2f}.")
                ps_prepare_resp = payment_stub.Prepare(ps_prepare_req, timeout=5.0)
                payment_vote_status = ps_prepare_resp.vote
                if payment_vote_status == payment_service_pb2.VOTE_COMMIT:
                    payment_prepared_successfully = True
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService VOTE_COMMIT.")
                else:
                    logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService VOTE_ABORT. Reason: {ps_prepare_resp.message}")
        except grpc.RpcError as e:
            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: gRPC error preparing PaymentService: {e.code()} - {e.details()}")
            payment_vote_status = payment_service_pb2.VOTE_ABORT # Treat RPC error as abort
        except Exception as e_inner:
            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Non-gRPC error preparing PaymentService: {e_inner}", exc_info=True)
            payment_vote_status = payment_service_pb2.VOTE_ABORT

        if payment_prepared_successfully:
            db_prepare_req = books_database_pb2.DBPrepareRequest(
                transaction_id=transaction_id, operations=db_operations
            )
            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending PrepareTransaction to BooksDatabaseService.")
            db_prepare_resp = self._call_db_service_rpc("PrepareTransaction", db_prepare_req)
            if db_prepare_resp and db_prepare_resp.vote == books_database_pb2.DB_VOTE_COMMIT:
                db_vote_status = books_database_pb2.DB_VOTE_COMMIT
                db_prepared_successfully = True
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService DB_VOTE_COMMIT.")
            else:
                db_vote_status = books_database_pb2.DB_VOTE_ABORT
                err_msg = db_prepare_resp.message if db_prepare_resp else "DB PrepareTransaction call failed or no response"
                logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService DB_VOTE_ABORT. Reason: {err_msg}")
        else:
             db_vote_status = books_database_pb2.DB_VOTE_ABORT
             logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Skipping DB Prepare as PaymentService did not VOTE_COMMIT or failed prepare.")

        # --- Decision Phase ---
        global_decision_is_commit = payment_prepared_successfully and db_prepared_successfully
        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Global decision is {'COMMIT' if global_decision_is_commit else 'ABORT'}.")

        # --- Commit/Abort Phase ---
        payment_final_ack_ok = False # Tracks if the final action (commit/abort) on payment was acked successfully
        db_final_ack_ok = False      # Tracks if the final action (commit/abort) on DB was acked successfully
        
        payment_channel_for_final_op = None
        payment_stub_for_final_op = None

        # Create channel for payment only if it was successfully prepared (meaning we might send Commit or Abort)
        if payment_prepared_successfully:
            try:
                payment_channel_for_final_op = grpc.insecure_channel(PAYMENT_SERVICE_ADDRESS)
                payment_stub_for_final_op = payment_service_pb2_grpc.PaymentServiceStub(payment_channel_for_final_op)
            except Exception as e_channel:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Failed to create PaymentService channel for Commit/Abort: {e_channel}", exc_info=True)
                # If channel fails, we can't send Commit/Abort to payment service.
                # This will result in payment_final_ack_ok remaining False.

        try: # Main try for commit/abort logic, finally closes channel
            if global_decision_is_commit:
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering COMMIT phase.")
                # Commit Payment Service
                if payment_prepared_successfully and payment_stub_for_final_op:
                    try:
                        ps_commit_req = payment_service_pb2.TransactionRequest(transaction_id=transaction_id)
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Commit to PaymentService.")
                        ps_commit_resp = payment_stub_for_final_op.Commit(ps_commit_req, timeout=5.0)
                        if ps_commit_resp.status == payment_service_pb2.ACK_SUCCESS:
                            payment_final_ack_ok = True
                            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Commit ACK_SUCCESS.")
                        else:
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Commit ACK_FAILURE. Reason: {ps_commit_resp.message}. CRITICAL ERROR.")
                    except Exception as e_ps_commit:
                        logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Error committing PaymentService: {e_ps_commit}", exc_info=True)
                elif payment_prepared_successfully: # Stub was not created due to channel error
                     logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Cannot commit PaymentService, channel/stub for commit phase unavailable.")
                
                # Commit Books Database Service
                if db_prepared_successfully and payment_final_ack_ok: # Only commit DB if it was prepared AND payment commit was OK
                    db_commit_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending CommitTransaction to BooksDatabaseService.")
                    db_commit_resp = self._call_db_service_rpc("CommitTransaction", db_commit_req)
                    if db_commit_resp and db_commit_resp.status == books_database_pb2.DB_ACK_SUCCESS:
                        db_final_ack_ok = True
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Commit DB_ACK_SUCCESS.")
                    else:
                        err_msg = db_commit_resp.message if db_commit_resp else "DB CommitTransaction call failed or no response"
                        logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Commit DB_ACK_FAILURE. Reason: {err_msg}. CRITICAL ERROR.")
                elif db_prepared_successfully: # DB was prepared, but payment commit failed
                    logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Skipping DB Commit as PaymentService commit failed. Attempting to Abort DB as it was prepared.")
                    db_abort_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                    self._call_db_service_rpc("AbortTransaction", db_abort_req) # Best effort abort DB

            else: # Global decision is ABORT
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering ABORT phase.")
                # Abort Payment Service
                if payment_prepared_successfully and payment_stub_for_final_op:
                    try:
                        ps_abort_req = payment_service_pb2.TransactionRequest(transaction_id=transaction_id)
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Abort to PaymentService.")
                        ps_abort_resp = payment_stub_for_final_op.Abort(ps_abort_req, timeout=5.0)
                        if ps_abort_resp.status == payment_service_pb2.ACK_SUCCESS:
                            payment_final_ack_ok = True
                            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Abort ACK_SUCCESS.")
                        else:
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Abort ACK_FAILURE. Reason: {ps_abort_resp.message}")
                    except Exception as e_ps_abort:
                        logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Error aborting PaymentService: {e_ps_abort}", exc_info=True)
                elif payment_prepared_successfully: # Stub was not created
                     logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Cannot abort PaymentService, channel/stub for abort phase unavailable.")
                else: # Payment was not successfully prepared, consider its abort "ok"
                    payment_final_ack_ok = True 
                
                # Abort Books Database Service
                if db_prepared_successfully:
                    db_abort_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending AbortTransaction to BooksDatabaseService.")
                    db_abort_resp = self._call_db_service_rpc("AbortTransaction", db_abort_req)
                    if db_abort_resp and db_abort_resp.status == books_database_pb2.DB_ACK_SUCCESS:
                        db_final_ack_ok = True
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Abort DB_ACK_SUCCESS.")
                    else:
                        err_msg = db_abort_resp.message if db_abort_resp else "DB AbortTransaction call failed or no response"
                        logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Abort DB_ACK_FAILURE. Reason: {err_msg}")
                else: # DB was not successfully prepared, consider its abort "ok"
                    db_final_ack_ok = True
        finally:
            if payment_channel_for_final_op:
                payment_channel_for_final_op.close()

        # --- Final Outcome Evaluation ---
        if global_decision_is_commit:
            if payment_final_ack_ok and db_final_ack_ok:
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} SUCCESSFULLY PROCESSED AND COMMITTED.")
                with self.lock: # Main RaftConsensus lock
                    self.processed_orders_count += 1
                logger.info(f"[{self.node_id}] Total orders successfully committed by this leader instance: {self.processed_orders_count}")
            else:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} FAILED COMMIT PHASE. PaymentFinalAckOK: {payment_final_ack_ok}, DBFinalAckOK: {db_final_ack_ok}. Manual intervention likely required.")
        else: # Global decision was ABORT
            if payment_final_ack_ok and db_final_ack_ok: # Both participants acknowledged the abort (or weren't prepared)
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} SUCCESSFULLY ABORTED.")
            else:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} FAILED ABORT PHASE. PaymentFinalAckOK: {payment_final_ack_ok}, DBFinalAckOK: {db_final_ack_ok}. State might be inconsistent.")
class OrderExecutorServicer(order_executor_pb2_grpc.OrderExecutorServiceServicer):
    def __init__(self, consensus_algorithm):
        self.consensus = consensus_algorithm
        
    def RequestVote(self, request, context):
        candidate_id = request.candidate_id
        term = request.term
        correlation_id = request.correlation_id
        logger.info(f"[{self.consensus.node_id}][{correlation_id}] Received VoteRequest from {candidate_id} for term {term}.")
        with self.consensus.lock:
            if term < self.consensus.current_term:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id} (term {term} < currentTerm {self.consensus.current_term}).")
                return order_executor_pb2.VoteResponse(vote_granted=False, term=self.consensus.current_term)
            if term > self.consensus.current_term:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Discovered higher term {term} from VoteRequest by {candidate_id}. Stepping down.")
                self.consensus._transition_to_follower(term)
            vote_granted_flag = False
            if self.consensus.voted_for is None or self.consensus.voted_for == candidate_id:
                if term == self.consensus.current_term:
                    self.consensus.voted_for = candidate_id
                    self.consensus.last_heartbeat_time = time.time()
                    vote_granted_flag = True
                    logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote GRANTED for {candidate_id} for term {term}.")
                else:
                    logger.warning(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id}. Term mismatch ({term} vs {self.consensus.current_term}) after potential step down.")
            else:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id} (already voted for {self.consensus.voted_for} in term {self.consensus.current_term}).")
            return order_executor_pb2.VoteResponse(vote_granted=vote_granted_flag, term=self.consensus.current_term)
            
    def Heartbeat(self, request, context):
        leader_id_from_hb = request.leader_id
        term_from_hb = request.term
        with self.consensus.lock:
            if term_from_hb < self.consensus.current_term:
                return order_executor_pb2.HeartbeatResponse(success=False, term=self.consensus.current_term)
            if term_from_hb >= self.consensus.current_term:
                if self.consensus.state != FOLLOWER or self.consensus.current_term < term_from_hb or self.consensus.leader_id != leader_id_from_hb:
                    logger.info(f"[{self.consensus.node_id}] Accepting HB from {leader_id_from_hb} (Term: {term_from_hb}). Updating state/leader.")
                    self.consensus._transition_to_follower(term_from_hb, new_leader_id=leader_id_from_hb)
                else:
                    self.consensus.last_heartbeat_time = time.time()
                return order_executor_pb2.HeartbeatResponse(success=True, term=self.consensus.current_term)
            return order_executor_pb2.HeartbeatResponse(success=False, term=self.consensus.current_term)
            
    def GetExecutorStatus(self, request, context):
        with self.consensus.lock:
            return order_executor_pb2.StatusResponse(
                executor_id=self.consensus.node_id,
                state=self.consensus.state,
                current_term=self.consensus.current_term,
                processed_orders=self.consensus.processed_orders_count,
                leader_id=self.consensus.leader_id or ""
            )

def serve():
    consensus_algorithm = RaftConsensus(node_id=EXECUTOR_ID, peers=PEERS)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    order_executor_pb2_grpc.add_OrderExecutorServiceServicer_to_server(
        OrderExecutorServicer(consensus_algorithm), server
    )
    server.add_insecure_port('[::]:50055')
    server.start()
    logger.info(f"Order Executor {EXECUTOR_ID} started on port 50055.")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        logger.info(f"Order Executor {EXECUTOR_ID} shutting down.")
        server.stop(0)
        consensus_algorithm.is_running = False

if __name__ == "__main__":
    serve()