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
import books_database_pb2 # NEW
import books_database_pb2_grpc # NEW


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


# Raft states
FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"

# For DB Raft Leader Discovery (same states)
DB_FOLLOWER, DB_CANDIDATE, DB_LEADER = "follower", "candidate", "leader" # Matching proto definition


class RaftConsensus:
    def __init__(self, node_id, peers):
        self.node_id = node_id
        self.peers = peers
        self.state = FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.leader_id = None
        self.election_timeout_duration = self._get_random_election_timeout_duration() # Renamed for clarity
        self.last_heartbeat_time = time.time() # Renamed for clarity
        self.votes_received_count = 0 # Renamed for clarity
        self.processed_orders_count = 0 # Renamed for clarity
        
        self.lock = threading.RLock()
        self.processing_order_flag = False # Renamed for clarity
        
        # --- NEW: Database Service Interaction Attributes ---
        self.db_node_addresses_str = os.environ.get("DB_NODE_ADDRESSES", "books_database_1:50060,books_database_2:50061,books_database_3:50062")
        self.db_node_addresses = [addr.strip() for addr in self.db_node_addresses_str.split(',') if addr.strip()]
        self.current_db_leader_address = None
        self.db_leader_lock = threading.Lock() # Specific lock for DB leader address
        # --- END NEW ---

        self.is_running = True # Renamed for clarity
        self.election_timer_thread = threading.Thread(target=self._run_election_timer_loop) # Renamed
        self.election_timer_thread.daemon = True
        self.election_timer_thread.start()
        
        self.leader_heartbeat_thread = None # Renamed
        
        logger.info(f"Executor {self.node_id} initialized. OE Peers: {self.peers}. DB Nodes: {self.db_node_addresses}")
        
    def _get_random_election_timeout_duration(self):
        return random.uniform(1.5, 3.0)
        
    def _run_election_timer_loop(self):
        while self.is_running:
            time.sleep(0.1) # Check frequently
            with self.lock:
                if self.state == LEADER:
                    continue # Leaders don't run election timers for themselves
                
                # Check if election timeout has occurred
                if time.time() - self.last_heartbeat_time > self.election_timeout_duration:
                    logger.info(f"[{self.node_id}] Election timeout! Last HB: {self.last_heartbeat_time}, Now: {time.time()}. Starting election.")
                    self._initiate_election() # Renamed
                    
    def _initiate_election(self):
        # Assumes self.lock is held
        self.state = CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id # Vote for self
        self.votes_received_count = 1 # Count self vote
        self.leader_id = None # No leader when candidate
        self.election_timeout_duration = self._get_random_election_timeout_duration() # Reset timeout for next round
        self.last_heartbeat_time = time.time() # Reset timer after becoming candidate
        
        logger.info(f"[{self.node_id}] Initiating election for term {self.current_term}.")
        
        for peer_address in self.peers:
            threading.Thread(target=self._send_vote_request_to_peer, args=(peer_address,)).start() # Renamed
                
    def _send_vote_request_to_peer(self, peer_address):
        correlation_id = str(uuid.uuid4())
        term_at_request_time = -1 # To ensure we are acting on the correct term's request
        
        with self.lock:
            if self.state != CANDIDATE:
                return # No longer a candidate, abort sending request
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
                response_pb = stub.RequestVote(request_pb, timeout=0.5) # Short timeout for vote requests
                
                with self.lock:
                    # Check if still a candidate and for the same term this request was for
                    if self.state != CANDIDATE or self.current_term != term_at_request_time:
                        logger.debug(f"[{self.node_id}][{correlation_id}] Vote response from {peer_address} is stale or state changed. Ignoring.")
                        return
                        
                    if response_pb.term > self.current_term:
                        logger.info(f"[{self.node_id}][{correlation_id}] Discovered higher term {response_pb.term} from vote response by {peer_address}. Stepping down.")
                        self._transition_to_follower(response_pb.term) # Renamed
                        return
                        
                    if response_pb.vote_granted:
                        logger.info(f"[{self.node_id}][{correlation_id}] Vote GRANTED by {peer_address} for term {self.current_term}.")
                        self.votes_received_count += 1
                        # Check for majority: (N/2) + 1 for N total nodes
                        if self.votes_received_count > (len(self.peers) + 1) / 2:
                            self._transition_to_leader() # Renamed
        except Exception as e:
            logger.error(f"[{self.node_id}][{correlation_id}] Error requesting vote from {peer_address}: {e}")

    def _transition_to_follower(self, new_term, new_leader_id=None):
        # Assumes self.lock is held
        logger.info(f"[{self.node_id}] Transitioning to FOLLOWER. Old Term: {self.current_term}, New Term: {new_term}. Old State: {self.state}")
        self.state = FOLLOWER
        self.current_term = new_term
        self.voted_for = None
        self.leader_id = new_leader_id # Can be None if stepping down due to higher term from candidate
        self.election_timeout_duration = self._get_random_election_timeout_duration()
        self.last_heartbeat_time = time.time() # Reset timer upon transitioning
        # If there was a leader_heartbeat_thread, it will stop due to state change check

    def _transition_to_leader(self):
        # Assumes self.lock is held
        if self.state != CANDIDATE: # Must be a candidate to become leader
            return

        self.state = LEADER
        self.leader_id = self.node_id # Leader is self
        logger.info(f"Node {self.node_id} PROMOTED TO LEADER for term {self.current_term}.")
        
        # NEW: Discover DB leader immediately upon becoming OE leader
        self._discover_db_leader_async() # Run in a new thread to not block Raft logic

        # Start sending heartbeats to peers
        if self.leader_heartbeat_thread is None or not self.leader_heartbeat_thread.is_alive():
            self.leader_heartbeat_thread = threading.Thread(target=self._send_heartbeats_as_leader_loop) # Renamed
            self.leader_heartbeat_thread.daemon = True
            self.leader_heartbeat_thread.start()
        
        # Start order processing loop (ensure only one is running)
        # This needs a more robust way to ensure only one processing loop is active per leader instance.
        # For now, let's assume this is called once when transitioning to leader.
        threading.Thread(target=self._process_orders_as_leader_loop, daemon=True).start() # Renamed
                
    def _send_heartbeats_as_leader_loop(self):
        while self.is_running:
            time.sleep(0.5) # Heartbeat interval
            current_term_for_hb = -1
            with self.lock:
                if self.state != LEADER:
                    logger.info(f"[{self.node_id}] No longer LEADER, stopping heartbeats thread.")
                    return # Exit thread
                current_term_for_hb = self.current_term
            
            correlation_id = str(uuid.uuid4())
            for peer_address in self.peers:
                # Each heartbeat to a peer in its own thread
                threading.Thread(target=self._send_single_heartbeat_to_peer, args=(peer_address, current_term_for_hb, correlation_id)).start() # Renamed
                    
    def _send_single_heartbeat_to_peer(self, peer_address, term, correlation_id):
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                request_pb = order_executor_pb2.HeartbeatRequest(
                    leader_id=self.node_id,
                    term=term,
                    correlation_id=correlation_id
                )
                # logger.debug(f"[{self.node_id}] Sending HB to {peer_address} for term {term}")
                response_pb = stub.Heartbeat(request_pb, timeout=0.3) # Short timeout for heartbeats
                
                with self.lock:
                    if response_pb.term > self.current_term:
                        logger.info(f"[{self.node_id}][{correlation_id}] Discovered higher term {response_pb.term} from HB response by {peer_address}. Stepping down.")
                        self._transition_to_follower(response_pb.term)
        except Exception: # Heartbeat failures are expected if a peer is down, log minimally or not at all.
            # logger.debug(f"[{self.node_id}] Failed to send HB to {peer_address}: {e}")
            pass
            
    def _process_orders_as_leader_loop(self):
        logger.info(f"[{self.node_id}] LEADER starting order processing loop.")
        while self.is_running:
            should_process = False
            with self.lock:
                if self.state != LEADER:
                    logger.info(f"[{self.node_id}] No longer LEADER, stopping order processing loop.")
                    return # Exit loop
                if not self.processing_order_flag:
                    self.processing_order_flag = True # Set flag indicating processing starts
                    should_process = True
            
            if should_process:
                try:
                    self._process_one_order_from_queue() # Renamed
                except Exception as e:
                    logger.error(f"[{self.node_id}] Unhandled error in _process_one_order_from_queue: {e}", exc_info=True)
                finally:
                    with self.lock:
                        self.processing_order_flag = False # Reset flag after processing
            
            time.sleep(1.0) # Delay between attempts to pick up an order
            
    # --- NEW: Database Interaction Methods ---
    def _discover_db_leader_async(self):
        """Wrapper to run discovery in a separate thread."""
        threading.Thread(target=self._discover_db_leader, daemon=True).start()

    def _discover_db_leader(self):
        """Discovers the leader of the BooksDatabase Raft group."""
        with self.db_leader_lock: # Lock specifically for current_db_leader_address
            self.current_db_leader_address = None # Force re-discovery

        logger.info(f"[{self.node_id}] OE Leader: Discovering BooksDatabase leader from {self.db_node_addresses}")
        discovered_leader_addr = None
        for addr in self.db_node_addresses:
            try:
                with grpc.insecure_channel(addr) as channel:
                    stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                    role_req = books_database_pb2.GetNodeRoleRequest()
                    role_resp = stub.GetNodeRole(role_req, timeout=0.5) # Short timeout for discovery
                    
                    if role_resp.role == DB_LEADER:
                        discovered_leader_addr = addr
                        logger.info(f"[{self.node_id}] OE Leader: BooksDatabase leader found at {addr} (DB Term: {role_resp.term})")
                        break # Found leader
                    elif role_resp.leader_id and role_resp.leader_id != addr:
                        # A follower might know the leader. This is a hint.
                        # For simplicity, we'll just iterate, but a more robust system could prioritize this hint.
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
        """Gets the current DB leader address, optionally retrying discovery."""
        with self.db_leader_lock:
            if self.current_db_leader_address:
                return self.current_db_leader_address
        
        if allow_rediscovery:
            if self._discover_db_leader(): # Attempt discovery
                with self.db_leader_lock:
                    return self.current_db_leader_address
        return None


    def _call_db_service_rpc(self, rpc_method_name, request_pb, max_retries=3):
        """Makes an RPC call to the BooksDatabase service leader with retry and leader rediscovery."""
        attempt = 0
        last_exception = None
        
        while attempt < max_retries:
            # Determine DB leader address to use for this attempt
            db_leader_addr = self._get_current_db_leader_address_with_retry(allow_rediscovery=(attempt > 0)) # Allow rediscovery on retries
            
            if not db_leader_addr:
                logger.error(f"[{self.node_id}] DB_CALL_FAIL: No DB leader found for {rpc_method_name}. Attempt {attempt+1}/{max_retries}.")
                attempt += 1
                time.sleep(0.2 * attempt) # Small backoff before retrying discovery
                continue

            logger.info(f"[{self.node_id}] DB_CALL: Attempting {rpc_method_name} on DB leader {db_leader_addr} (Attempt {attempt+1})")
            try:
                with grpc.insecure_channel(db_leader_addr) as channel:
                    stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                    method_to_call = getattr(stub, rpc_method_name)
                    # Timeout for DB operations needs to be reasonable, e.g., 2-5 seconds
                    response = method_to_call(request_pb, timeout=3.0) 
                    logger.info(f"[{self.node_id}] DB_CALL_SUCCESS: {rpc_method_name} on {db_leader_addr} successful.")
                    return response # Successful call
            except grpc.RpcError as e:
                last_exception = e
                logger.warning(f"[{self.node_id}] DB_CALL_RPC_ERROR: {rpc_method_name} on {db_leader_addr} failed: {e.code()} - {e.details()}")
                if e.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL, grpc.StatusCode.DEADLINE_EXCEEDED):
                    # These errors might indicate the leader changed or node is down. Force rediscovery.
                    with self.db_leader_lock:
                        self.current_db_leader_address = None 
                    logger.info(f"[{self.node_id}] DB_CALL: Cleared current DB leader due to RPC error. Will attempt rediscovery.")
                elif e.code() == grpc.StatusCode.ABORTED and "Not the leader" in e.details():
                     with self.db_leader_lock: # Explicitly told not leader
                        self.current_db_leader_address = None
                     logger.info(f"[{self.node_id}] DB_CALL: DB node {db_leader_addr} reported it is not the leader. Retrying discovery.")
                else:
                    # For other errors (like business logic errors if they raised RpcError, though typically handled in response fields)
                    # we might not want to retry, or handle them differently.
                    # If the proto has `success=false` for business errors, this RpcError block might not catch them.
                    logger.error(f"[{self.node_id}] DB_CALL_UNHANDLED_RPC_ERROR: {rpc_method_name} on {db_leader_addr} - {e.code()}: {e.details()}")
                    # Depending on the error, might re-raise or return None immediately.
                    # For now, continue to retry for most RPC errors.
                    pass
            except Exception as ex: # Catch other unexpected errors during the call
                last_exception = ex
                logger.error(f"[{self.node_id}] DB_CALL_UNEXPECTED_ERROR: Calling {rpc_method_name} on {db_leader_addr}: {ex}", exc_info=True)
                # Possibly invalidate leader here too if it's a network-related Python error
                with self.db_leader_lock:
                    self.current_db_leader_address = None

            attempt += 1
            time.sleep(0.3 * attempt) # Slightly longer backoff for retries involving potential rediscovery

        logger.error(f"[{self.node_id}] DB_CALL_FINAL_FAIL: {rpc_method_name} failed after {max_retries} retries. Last error: {last_exception}")
        return None # Indicate failure after all retries

    def _process_one_order_from_queue(self):
        correlation_id = str(uuid.uuid4())
        logger.info(f"[{self.node_id}][{correlation_id}] OE Leader: Attempting to dequeue an order.")
        
        order_id = None
        order_data = None
        
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
                order_data = dequeue_response.order_data # This is an OrderData protobuf message
                
                logger.info(f"[{correlation_id}] Processing order {order_id} with data: {str(order_data)[:200]}...") # Log truncated string representation

                # --- Distributed Transaction (2PC) with Payment Service ---
                transaction_id = str(uuid.uuid4())
                payment_success = False

                try:
                    with grpc.insecure_channel(PAYMENT_SERVICE_ADDRESS) as payment_channel:
                        payment_stub = payment_service_pb2_grpc.PaymentServiceStub(payment_channel)

                        # --- Prepare Phase ---
                        # TODO: Extract actual amount from order_data if available
                        amount = 10.0  # Dummy amount for now

                        prepare_request = payment_service_pb2.PaymentPrepareRequest(
                            transaction_id=transaction_id,
                            order_id=order_id,
                            amount=amount
                        )
                        logger.info(f"[{correlation_id}] TX[{transaction_id}]: Sending Prepare to payment service for order {order_id}")
                        prepare_response = payment_stub.Prepare(prepare_request, timeout=5.0)

                        if prepare_response.vote == payment_service_pb2.VOTE_COMMIT:
                            logger.info(f"[{correlation_id}] TX[{transaction_id}]: Payment service VOTE_COMMIT for order {order_id}")

                            # --- Commit Phase ---
                            commit_request = payment_service_pb2.TransactionRequest(transaction_id=transaction_id)
                            logger.info(f"[{correlation_id}] TX[{transaction_id}]: Sending Commit to payment service for order {order_id}")
                            commit_response = payment_stub.Commit(commit_request, timeout=5.0)

                            if commit_response.status == payment_service_pb2.ACK_SUCCESS:
                                logger.info(f"[{correlation_id}] TX[{transaction_id}]: Payment service ACK_SUCCESS for Commit on order {order_id}")
                                payment_success = True
                            else:
                                logger.error(f"[{correlation_id}] TX[{transaction_id}]: Payment service ACK_FAILURE for Commit on order {order_id}. Message: {commit_response.message}. CRITICAL: Manual intervention may be needed.")
                                # TODO: Implement compensation/rollback for coordinator if payment commit fails after prepare.
                                # For now, just log and fail the order.
                        else:  # VOTE_ABORT or other issue
                            logger.warning(f"[{correlation_id}] TX[{transaction_id}]: Payment service VOTE_ABORT for Prepare on order {order_id}. Message: {prepare_response.message}")
                            # No explicit Abort message needed to payment_service if it voted Abort.
                            # If coordinator timed out waiting for Prepare, it might send Abort.

                except grpc.RpcError as e:
                    logger.error(f"[{correlation_id}] TX[{transaction_id}]: gRPC error during 2PC with payment service for order {order_id}: {e.code()} - {e.details()}")
                    # If Prepare succeeded but Commit call failed/timed out, this is a dangerous state.
                    # The coordinator might need to retry Commit or eventually Abort if payment service is unreachable.
                    # For now, we assume failure.
                except Exception as e:
                    logger.error(f"[{correlation_id}] TX[{transaction_id}]: Non-gRPC error during 2PC with payment service for order {order_id}: {e}")

                if payment_success:
                    logger.info(f"[{correlation_id}] TX[{transaction_id}]: Distributed transaction for order {order_id} successful. Proceeding with local execution.")
                    
                    # Simulate local order processing steps (e.g., update inventory, finalize in local DB)
                    logger.info(f"[{correlation_id}] Order {order_id} is being executed (local steps)...")
                    time.sleep(0.5) # Simulate local work
                    logger.info(f"[{correlation_id}] Order {order_id} local execution completed successfully")
                    
                    with self.lock:
                        self.processed_orders_count += 1
                else:
                    logger.error(f"[{correlation_id}] TX[{transaction_id}]: Distributed transaction for order {order_id} FAILED. Order will not be processed.")
                    # TODO: Handle failed transaction (e.g., notify user, requeue for retry with backoff, move to dead-letter queue)
        

        except grpc.RpcError as e:
            logger.error(f"[{self.node_id}][{correlation_id}] OE Leader: RPC error interacting with queue service: {e.code()} - {e.details()}", exc_info=True)
            return # Cannot proceed if queue interaction fails
        except Exception as e_gen:
            logger.error(f"[{self.node_id}][{correlation_id}] OE Leader: Unexpected error during queue interaction: {e_gen}", exc_info=True)
            return

        # If order successfully dequeued, proceed to process it with 2PC
        if order_id and order_data:
            transaction_id = str(uuid.uuid4())
            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Starting 2PC for order {order_id} with {len(order_data.items)} items.")

            # 1. Construct BookOperations for DB Prepare from order_data.items
            db_operations = []
            valid_order_items = True
            for item in order_data.items:
                book_id_in_db = None
                item_name_lower = item.name.lower()
                # This mapping logic should ideally be more robust or data-driven
                if "book a" in item_name_lower: book_id_in_db = "book_101_clean_code"
                elif "pragmatic programmer" in item_name_lower: book_id_in_db = "book_102_pragmatic_programmer"
                elif "design patterns" in item_name_lower: book_id_in_db = "book_103_design_patterns"
                elif "domain-driven design" in item_name_lower: book_id_in_db = "book_104_domain_driven_design"
                
                if not book_id_in_db:
                    logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Cannot map item '{item.name}' to a DB book_id. Aborting order pre-2PC.")
                    valid_order_items = False
                    break
                db_operations.append(books_database_pb2.BookOperation(book_id=book_id_in_db, quantity_change=-item.quantity))
            
            if not valid_order_items:
                # Order cannot be processed, no 2PC initiated.
                # Consider this a failed order.
                return

            # --- 2PC State Variables ---
            payment_vote = None # payment_service_pb2.VOTE_UNSPECIFIED
            db_vote = None      # books_database_pb2.DB_VOTE_UNSPECIFIED
            
            payment_prepared_successfully = False
            db_prepared_successfully = False

            # --- Prepare Phase ---
            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering PREPARE phase.")
            
            # Prepare Payment Service
            try:
                with grpc.insecure_channel(PAYMENT_SERVICE_ADDRESS) as payment_channel:
                    payment_stub = payment_service_pb2_grpc.PaymentServiceStub(payment_channel)
                    # TODO: Extract actual amount from order_data if available/needed by payment service
                    amount = 10.0  # Dummy amount for now
                    ps_prepare_req = payment_service_pb2.PaymentPrepareRequest(
                        transaction_id=transaction_id, order_id=order_id, amount=amount
                    )
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Prepare to PaymentService.")
                    ps_prepare_resp = payment_stub.Prepare(ps_prepare_req, timeout=5.0)
                    payment_vote = ps_prepare_resp.vote
                    if payment_vote == payment_service_pb2.VOTE_COMMIT:
                        payment_prepared_successfully = True
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService VOTE_COMMIT.")
                    else:
                        logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService VOTE_ABORT. Reason: {ps_prepare_resp.message}")
            except grpc.RpcError as e:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: gRPC error preparing PaymentService: {e.code()} - {e.details()}")
                payment_vote = payment_service_pb2.VOTE_ABORT # Treat RPC error as abort
            except Exception as e:
                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Non-gRPC error preparing PaymentService: {e}", exc_info=True)
                payment_vote = payment_service_pb2.VOTE_ABORT

            # Prepare Books Database Service (only if payment didn't immediately vote abort)
            if payment_vote == payment_service_pb2.VOTE_COMMIT:
                db_prepare_req = books_database_pb2.DBPrepareRequest(
                    transaction_id=transaction_id, operations=db_operations
                )
                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending PrepareTransaction to BooksDatabaseService.")
                db_prepare_resp = self._call_db_service_rpc("PrepareTransaction", db_prepare_req) # Uses leader discovery
                
                if db_prepare_resp and db_prepare_resp.vote == books_database_pb2.DB_VOTE_COMMIT:
                    db_vote = books_database_pb2.DB_VOTE_COMMIT
                    db_prepared_successfully = True
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService DB_VOTE_COMMIT.")
                else:
                    db_vote = books_database_pb2.DB_VOTE_ABORT
                    err_msg = db_prepare_resp.message if db_prepare_resp else "PrepareTransaction call failed or no response"
                    logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService DB_VOTE_ABORT. Reason: {err_msg}")
            else: # Payment service already aborted or failed prepare
                 db_vote = books_database_pb2.DB_VOTE_ABORT # No need to call DB if payment failed
                 logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Skipping DB Prepare as PaymentService did not VOTE_COMMIT.")


            # --- Decision Phase ---
            global_decision_is_commit = payment_prepared_successfully and db_prepared_successfully
            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Global decision is {'COMMIT' if global_decision_is_commit else 'ABORT'}.")

            # --- Commit/Abort Phase ---
            payment_final_ack_ok = False
            db_final_ack_ok = False
            
            payment_channel = None
            payment_stub = None
            
            # Create payment channel/stub only if needed for Commit/Abort
            # This avoids redundant channel creation within the commit/abort logic below
            if payment_prepared_successfully:
                try:
                    payment_channel = grpc.insecure_channel(PAYMENT_SERVICE_ADDRESS)
                    payment_stub = payment_service_pb2_grpc.PaymentServiceStub(payment_channel)
                except Exception as e:
                     logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Failed to create PaymentService channel for Commit/Abort phase: {e}", exc_info=True)
                     # If channel fails, we cannot proceed with commit/abort for payment service. Mark as failed.
                     payment_final_ack_ok = False # Cannot proceed, will lead to failed commit/abort

            try: # Use try-finally to ensure channel closure if it was opened
                if global_decision_is_commit:
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering COMMIT phase.")
                    # Commit Payment Service
                    if payment_stub: # Check if stub was created successfully
                        try:
                            ps_commit_req = payment_service_pb2.TransactionRequest(transaction_id=transaction_id)
                            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Commit to PaymentService.")
                            ps_commit_resp = payment_stub.Commit(ps_commit_req, timeout=5.0)
                            if ps_commit_resp.status == payment_service_pb2.ACK_SUCCESS:
                                payment_final_ack_ok = True
                                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Commit ACK_SUCCESS.")
                            else:
                                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Commit ACK_FAILURE. Reason: {ps_commit_resp.message}. CRITICAL ERROR.")
                        except Exception as e:
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Error committing PaymentService: {e}", exc_info=True)
                            payment_final_ack_ok = False # Explicitly mark failure on exception
                    else: # Stub creation failed earlier or wasn't needed (prepare failed)
                         if payment_prepared_successfully: # Log error only if we expected to commit
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Cannot commit PaymentService, channel/stub unavailable.")
                         payment_final_ack_ok = False # Mark as failed if prepare was successful but stub failed

                    # Commit Books Database Service (only if payment commit was OK, or handle partial failures)
                    if payment_final_ack_ok: # Proceed only if payment commit succeeded
                        db_commit_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending CommitTransaction to BooksDatabaseService.")
                        db_commit_resp = self._call_db_service_rpc("CommitTransaction", db_commit_req)
                        if db_commit_resp and db_commit_resp.status == books_database_pb2.DB_ACK_SUCCESS:
                            db_final_ack_ok = True
                            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Commit DB_ACK_SUCCESS.")
                        else:
                            err_msg = db_commit_resp.message if db_commit_resp else "CommitTransaction call failed or no response"
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Commit DB_ACK_FAILURE. Reason: {err_msg}. CRITICAL ERROR.")
                            db_final_ack_ok = False # Explicitly mark failure
                    else: # Payment commit failed
                        logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Skipping DB Commit as PaymentService commit failed. This is a divergence scenario requiring robust handling (e.g. compensation).")
                        db_final_ack_ok = False # DB commit did not happen
                        # Attempt to Abort DB since it was prepared but payment commit failed
                        if db_prepared_successfully:
                            logger.warning(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Attempting to Abort BooksDatabase due to PaymentService commit failure.")
                            db_abort_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                            self._call_db_service_rpc("AbortTransaction", db_abort_req) # Best effort abort

                else: # Global decision is ABORT
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Entering ABORT phase.")
                    # Abort Payment Service (if it was successfully prepared)
                    if payment_prepared_successfully:
                        if payment_stub: # Check if stub was created successfully
                            try:
                                ps_abort_req = payment_service_pb2.TransactionRequest(transaction_id=transaction_id)
                                logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending Abort to PaymentService.")
                                ps_abort_resp = payment_stub.Abort(ps_abort_req, timeout=5.0)
                                if ps_abort_resp.status == payment_service_pb2.ACK_SUCCESS:
                                    payment_final_ack_ok = True # Abort was successful
                                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Abort ACK_SUCCESS.")
                                else:
                                    logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: PaymentService Abort ACK_FAILURE. Reason: {ps_abort_resp.message}")
                                    payment_final_ack_ok = False # Explicitly mark failure
                            except Exception as e:
                                logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Error aborting PaymentService: {e}", exc_info=True)
                                payment_final_ack_ok = False # Explicitly mark failure
                        else: # Stub creation failed earlier
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Cannot abort PaymentService, channel/stub unavailable.")
                            payment_final_ack_ok = False # Mark as failed
                    else: # Payment was not successfully prepared, so it's implicitly aborted from its view
                        payment_final_ack_ok = True 
                    
                    # Abort Books Database Service (if it was successfully prepared)
                    if db_prepared_successfully:
                        db_abort_req = books_database_pb2.DBTransactionRequest(transaction_id=transaction_id)
                        logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: Sending AbortTransaction to BooksDatabaseService.")
                        db_abort_resp = self._call_db_service_rpc("AbortTransaction", db_abort_req)
                        if db_abort_resp and db_abort_resp.status == books_database_pb2.DB_ACK_SUCCESS:
                            db_final_ack_ok = True # Abort was successful
                            logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Abort DB_ACK_SUCCESS.")
                        else:
                            err_msg = db_abort_resp.message if db_abort_resp else "AbortTransaction call failed or no response"
                            logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: BooksDatabaseService Abort DB_ACK_FAILURE. Reason: {err_msg}")
                            db_final_ack_ok = False # Explicitly mark failure
                    else: # DB was not successfully prepared
                        db_final_ack_ok = True
            finally:
                # Ensure payment channel is closed if it was opened
                if payment_channel:
                    payment_channel.close()

            # --- Final Outcome Evaluation ---
            if global_decision_is_commit:
                if payment_final_ack_ok and db_final_ack_ok:
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} SUCCESSFULLY PROCESSED AND COMMITTED.")
                    with self.lock:
                        self.processed_orders_count += 1
                    logger.info(f"[{self.node_id}] Total orders processed by this leader instance: {self.processed_orders_count}")
                else:
                    logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} FAILED COMMIT PHASE. PaymentAckOK: {payment_final_ack_ok}, DBAckOK: {db_final_ack_ok}. Manual intervention likely required.")
            else: # Global decision was ABORT
                if payment_final_ack_ok and db_final_ack_ok:
                    logger.info(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} SUCCESSFULLY ABORTED.")
                else:
                    logger.error(f"[{self.node_id}][{correlation_id}] TX[{transaction_id}]: ORDER {order_id} FAILED ABORT PHASE. PaymentAckOK: {payment_final_ack_ok}, DBAckOK: {db_final_ack_ok}. State might be inconsistent.")

class OrderExecutorServicer(order_executor_pb2_grpc.OrderExecutorServiceServicer):
    def __init__(self, consensus_algorithm): # Renamed for clarity
        self.consensus = consensus_algorithm # Instance of RaftConsensus
        
    def RequestVote(self, request, context):
        # Called by other OE nodes when they are candidates
        candidate_id = request.candidate_id
        term = request.term
        correlation_id = request.correlation_id
        
        logger.info(f"[{self.consensus.node_id}][{correlation_id}] Received VoteRequest from {candidate_id} for term {term}.")
        
        with self.consensus.lock:
            # Rule 1: Reply false if term < currentTerm
            if term < self.consensus.current_term:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id} (term {term} < currentTerm {self.consensus.current_term}).")
                return order_executor_pb2.VoteResponse(vote_granted=False, term=self.consensus.current_term)
                
            # If request term is greater, transition to follower and update term
            if term > self.consensus.current_term:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Discovered higher term {term} from VoteRequest by {candidate_id}. Stepping down.")
                self.consensus._transition_to_follower(term) # No new leader known yet from this vote request
                
            # Rule 2: If votedFor is null or candidateId, and candidate’s log is at least as up-to-date as receiver’s log, grant vote
            # (Log up-to-dateness check is omitted in this simplified Raft for leader election only)
            vote_granted_flag = False
            if self.consensus.voted_for is None or self.consensus.voted_for == candidate_id:
                if term == self.consensus.current_term: # Must be for the current (possibly updated) term
                    self.consensus.voted_for = candidate_id
                    self.consensus.last_heartbeat_time = time.time()  # Reset election timer as we are granting a vote
                    vote_granted_flag = True
                    logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote GRANTED for {candidate_id} for term {term}.")
                else: # Should not happen if term logic is correct, but defensive.
                    logger.warning(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id}. Term mismatch ({term} vs {self.consensus.current_term}) after potential step down.")
            else:
                logger.info(f"[{self.consensus.node_id}][{correlation_id}] Vote DENIED for {candidate_id} (already voted for {self.consensus.voted_for} in term {self.consensus.current_term}).")

            return order_executor_pb2.VoteResponse(vote_granted=vote_granted_flag, term=self.consensus.current_term)
            
    def Heartbeat(self, request, context):
        # Called by the OE Leader to assert authority and prevent new elections
        leader_id_from_hb = request.leader_id
        term_from_hb = request.term
        # correlation_id = request.correlation_id # Use if needed for detailed logging

        # logger.debug(f"[{self.consensus.node_id}] Received HB from {leader_id_from_hb} for term {term_from_hb}.")

        with self.consensus.lock:
            # Rule 1: Reply false if term < currentTerm
            if term_from_hb < self.consensus.current_term:
                # logger.debug(f"[{self.consensus.node_id}] HB REJECTED from {leader_id_from_hb} (term {term_from_hb} < currentTerm {self.consensus.current_term}).")
                return order_executor_pb2.HeartbeatResponse(success=False, term=self.consensus.current_term)
            
            # If HB term is greater or equal, and we are not already following this leader for this term
            if term_from_hb >= self.consensus.current_term:
                if self.consensus.state != FOLLOWER or self.consensus.current_term < term_from_hb or self.consensus.leader_id != leader_id_from_hb:
                    # This implies a transition to follower if not already, or updating to new leader/term
                    logger.info(f"[{self.consensus.node_id}] Accepting HB from {leader_id_from_hb} (Term: {term_from_hb}). Updating state/leader.")
                    self.consensus._transition_to_follower(term_from_hb, new_leader_id=leader_id_from_hb)
                else: # Already following this leader for this term, just reset timer
                    self.consensus.last_heartbeat_time = time.time()

                # logger.debug(f"[{self.consensus.node_id}] HB ACCEPTED from {leader_id_from_hb}. Current leader: {self.consensus.leader_id}, term: {self.consensus.current_term}")
                return order_executor_pb2.HeartbeatResponse(success=True, term=self.consensus.current_term)
            
            # Should not be reached if logic is correct
            return order_executor_pb2.HeartbeatResponse(success=False, term=self.consensus.current_term)

            
    def GetExecutorStatus(self, request, context):
        # Provides status of this OE node
        # correlation_id = request.correlation_id # Use if needed

        with self.consensus.lock:
            return order_executor_pb2.StatusResponse(
                executor_id=self.consensus.node_id,
                state=self.consensus.state,
                current_term=self.consensus.current_term,
                processed_orders=self.consensus.processed_orders_count, # Use the correct counter
                leader_id=self.consensus.leader_id or "" # Ensure leader_id is string
            )

def serve():
    # Initialize Raft consensus algorithm for this Order Executor node
    consensus_algorithm = RaftConsensus(node_id=EXECUTOR_ID, peers=PEERS)
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    order_executor_pb2_grpc.add_OrderExecutorServiceServicer_to_server(
        OrderExecutorServicer(consensus_algorithm), server
    )
    server.add_insecure_port('[::]:50055') # Port for this OE node's gRPC service
    server.start()
    logger.info(f"Order Executor {EXECUTOR_ID} started on port 50055.")
    try:
        while True:
            time.sleep(86400) # Keep main thread alive
    except KeyboardInterrupt:
        logger.info(f"Order Executor {EXECUTOR_ID} shutting down.")
        server.stop(0)
        consensus_algorithm.is_running = False # Signal threads to stop


if __name__ == "__main__":
    serve()
