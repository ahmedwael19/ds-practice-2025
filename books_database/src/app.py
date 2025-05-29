"""
Books Database Service


Author: Ahmed Soliman, Buraq Khan
Date: 2025-05-08
"""
import grpc
import logging
import os
import sys
import time
import uuid
import random
import threading
from concurrent import futures
from collections import defaultdict

# OpenTelemetry Imports
from opentelemetry import trace, metrics, context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics._internal.measurement import Measurement

# --- Protobuf Imports ---
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
books_database_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/books_database'))
sys.path.insert(0, books_database_grpc_path)

import books_database_pb2
import books_database_pb2_grpc

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("books_database")

# --- OpenTelemetry Setup ---
SERVICE_NAME = "books-database-service"
resource = Resource.create({"service.name": SERVICE_NAME})

# Configure TracerProvider
trace_exporter = OTLPSpanExporter(endpoint="http://observability:4318/v1/traces")
span_processor = BatchSpanProcessor(trace_exporter)
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(SERVICE_NAME)

# Configure MeterProvider
metric_exporter = OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
metric_reader = PeriodicExportingMetricReader(metric_exporter)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(SERVICE_NAME)

# Define Metrics (moved to __init__ for proper self binding for gauge)
books_read_counter = meter.create_counter(
    name="books_read_total",
    description="Total number of books read from the database",
    unit="1"
)
books_in_stock_updowncounter = meter.create_up_down_counter(
    name="books_in_stock",
    description="Current number of books in stock",
    unit="1"
)
read_stock_latency_histogram = meter.create_histogram(
    name="read_stock_latency_seconds",
    description="Latency of ReadStock operations",
    unit="s"
)

# --- Raft Constants (can be shared or adapted from order_executor) ---

# --- Raft Constants (can be shared or adapted from order_executor) ---
FOLLOWER, CANDIDATE, LEADER = "follower", "candidate", "leader"
HEARTBEAT_INTERVAL = 0.5  # seconds
MIN_ELECTION_TIMEOUT = 1.5
MAX_ELECTION_TIMEOUT = 3.0

class RaftNode:
    def __init__(self, node_id, peers, db_service_instance):
        self.node_id = node_id
        self.peers = peers # list of peer addresses (e.g., "books_database_2:50061")
        self.db_service_instance = db_service_instance # To call ApplyCommit on DB layer

        self.current_term = 0
        self.voted_for = None
        self.state = FOLLOWER
        self.leader_id = None

        self.election_timeout_value = self._get_random_election_timeout()
        self.last_heartbeat_time = time.time()
        self.votes_received = set()

        self.lock = threading.RLock()
        
        self.heartbeat_thread = threading.Thread(target=self._send_heartbeats_periodically, daemon=True)
        self.election_timer_thread = threading.Thread(target=self._run_election_timer, daemon=True)
        self.running = True

        logger.info(f"[{self.node_id}] RaftNode initialized. Peers: {self.peers}")

    def start(self):
        self.election_timer_thread.start()
        self.heartbeat_thread.start()
        logger.info(f"[{self.node_id}] RaftNode started.")

    def _get_random_election_timeout(self):
        return random.uniform(MIN_ELECTION_TIMEOUT, MAX_ELECTION_TIMEOUT)

    def _reset_election_timer(self):
        with self.lock:
            self.last_heartbeat_time = time.time()
            self.election_timeout_value = self._get_random_election_timeout()

    def _run_election_timer(self):
        while self.running:
            time.sleep(0.1) # Check frequently
            with self.lock:
                if self.state == LEADER:
                    continue
                if time.time() - self.last_heartbeat_time > self.election_timeout_value:
                    logger.info(f"[{self.node_id}] Election timeout! Last heartbeat: {self.last_heartbeat_time}, Current: {time.time()}")
                    self._start_election()

    def _start_election(self):
        with self.lock:
            if self.state == LEADER: return # Should not happen if timer logic is correct

            self.state = CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received = {self.node_id} # Vote for self
            self.leader_id = None
            self._reset_election_timer()
            logger.info(f"[{self.node_id}] Starting election for term {self.current_term}. Voted for self.")

            # Request votes from peers
            for peer_addr in self.peers:
                threading.Thread(target=self._send_request_vote_to_peer, args=(peer_addr, self.current_term)).start()


    def _send_request_vote_to_peer(self, peer_addr, term_of_election):
        try:
            with grpc.insecure_channel(peer_addr) as channel:
                stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                req = books_database_pb2.DBVoteRequest(term=term_of_election, candidate_id=self.node_id)
                logger.debug(f"[{self.node_id}] Requesting vote from {peer_addr} for term {term_of_election}")
                resp = stub.RequestVote(req, timeout=0.5) # Short timeout for vote requests

                with self.lock:
                    if self.state != CANDIDATE or self.current_term != term_of_election:
                        logger.debug(f"[{self.node_id}] No longer candidate or term changed while waiting for vote from {peer_addr}")
                        return

                    if resp.term > self.current_term:
                        logger.info(f"[{self.node_id}] Discovered higher term {resp.term} from {peer_addr}'s vote response. Stepping down.")
                        self._step_down(resp.term)
                    elif resp.vote_granted and resp.term == self.current_term:
                        self.votes_received.add(peer_addr) # Assuming peer_addr can serve as voter_id for simplicity
                        logger.info(f"[{self.node_id}] Vote granted by {peer_addr}. Votes: {len(self.votes_received)}/{((len(self.peers) + 1) // 2) + 1}")
                        if len(self.votes_received) > (len(self.peers) + 1) / 2:
                            self._become_leader()
        except Exception as e:
            logger.error(f"[{self.node_id}] Failed to request vote from {peer_addr}: {e}")


    def _become_leader(self):
        # Assumes lock is held
        if self.state != CANDIDATE: return

        self.state = LEADER
        self.leader_id = self.node_id
        logger.info(f"[{self.node_id}] BECAME LEADER for term {self.current_term}!")
        # Immediately send heartbeats to assert leadership
        self._send_heartbeats_to_all_peers()


    def _send_heartbeats_periodically(self):
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)
            with self.lock:
                if self.state == LEADER:
                    self._send_heartbeats_to_all_peers()
    
    def _send_heartbeats_to_all_peers(self):
        # Assumes lock might be held by caller or needs to be acquired if called directly by timer
        # For simplicity, this is called when self.state is LEADER
        current_term_for_hb = self.current_term # Capture term under lock
        for peer_addr in self.peers:
            threading.Thread(target=self._send_append_entries_to_peer, args=(peer_addr, current_term_for_hb, True)).start()

    def _send_append_entries_to_peer(self, peer_addr, term, is_heartbeat=False):
        # This simplified AppendEntries is mostly for heartbeats
        try:
            with grpc.insecure_channel(peer_addr) as channel:
                stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                # For heartbeat, entries list is empty
                req = books_database_pb2.DBAppendEntriesRequest(term=term, leader_id=self.node_id)
                if is_heartbeat:
                     logger.debug(f"[{self.node_id}] Sending HEARTBEAT to {peer_addr} for term {term}")

                resp = stub.AppendEntries(req, timeout=0.3)

                with self.lock:
                    if resp.term > self.current_term:
                        logger.info(f"[{self.node_id}] Discovered higher term {resp.term} from {peer_addr}'s AppendEntries response. Stepping down.")
                        self._step_down(resp.term)
                    # Add more logic here if handling actual log replication failures (resp.success == False)
        except Exception as e:
            if is_heartbeat:
                logger.debug(f"[{self.node_id}] Failed to send heartbeat to {peer_addr}: {e}")
            else:
                logger.error(f"[{self.node_id}] Failed to send AppendEntries to {peer_addr}: {e}")


    def _step_down(self, new_term):
        # Assumes lock is held
        logger.info(f"[{self.node_id}] Stepping down to Follower. Old term: {self.current_term}, New term: {new_term}")
        self.current_term = new_term
        self.state = FOLLOWER
        self.voted_for = None
        self.leader_id = None # Will be updated by heartbeat from new leader
        self._reset_election_timer() # Important to reset timer after stepping down

    def handle_request_vote(self, term, candidate_id):
        with self.lock:
            if term < self.current_term:
                logger.info(f"[{self.node_id}] Vote denied for {candidate_id} (term {term} < current {self.current_term})")
                return self.current_term, False
            if term > self.current_term:
                self._step_down(term)
                # Fall through to grant vote if not voted yet in this new term

            vote_granted = False
            if self.voted_for is None or self.voted_for == candidate_id:
                self.voted_for = candidate_id
                vote_granted = True
                self._reset_election_timer() # Granting vote means we trust this candidate might become leader
                logger.info(f"[{self.node_id}] Vote GRANTED for {candidate_id} for term {term}")
            else:
                logger.info(f"[{self.node_id}] Vote DENIED for {candidate_id} (term {term}, already voted for {self.voted_for})")
            
            return self.current_term, vote_granted

    def handle_append_entries(self, term, leader_id): # Simplified for heartbeat
        with self.lock:
            if term < self.current_term:
                logger.debug(f"[{self.node_id}] Rejected AppendEntries from {leader_id} (term {term} < current {self.current_term})")
                return self.current_term, False
            
            # If terms are same, or request term is higher, reset timer and update leader
            self._reset_election_timer()
            if term > self.current_term:
                self._step_down(term) # This also updates self.current_term
            
            self.state = FOLLOWER # Even if candidate, heartbeat from valid leader makes it follower
            self.leader_id = leader_id
            logger.debug(f"[{self.node_id}] Heartbeat accepted from leader {leader_id} for term {term}. Current Leader_id: {self.leader_id}")
            return self.current_term, True

class BooksDatabaseServiceServicer(books_database_pb2_grpc.BooksDatabaseServiceServicer):
    def __init__(self):
        self.node_id = os.environ.get("DB_NODE_ID", f"db_node_{uuid.uuid4().hex[:4]}")
        peers_str = os.environ.get("DB_PEER_ADDRESSES", "")
        self.peer_addresses = [p.strip() for p in peers_str.split(',') if p.strip()]
        
        self.raft_node = RaftNode(self.node_id, self.peer_addresses, self)
        
        self.datastore = { # Initial stock
            "book_101_clean_code": 10,
            "book_102_pragmatic_programmer": 5,
            "book_103_design_patterns": 15,
            "book_104_domain_driven_design": 3
        }
        self.key_locks = defaultdict(threading.Lock) #if multiple operations  calls or operations within different CommitTransaction calls target the same book_id at the primary, 
        # they are serialized for that specific book. This prevents race conditions on the stock count for individual books.
        self.pending_replications = {} # op_id -> {count, event, start_time}
        self.replication_lock = threading.Lock()

        # For 2PC
        self.active_2pc_transactions = {} # transaction_id -> {"state": "PREPARED", "operations": [...]}
        self.transactions_lock = threading.Lock() # Lock for active_2pc_transactions . BONUS!

        logger.info(f"[{self.node_id}] BooksDatabaseService initialized. Datastore: {self.datastore}")
        self.raft_node.start()

        # Define and register asynchronous gauge for active 2PC transactions inside __init__
        self.active_2pc_transactions_gauge = meter.create_observable_gauge(
            name="active_2pc_transactions_gauge",
            callbacks=[self._get_active_2pc_transactions_count],
            description="Number of active 2PC transactions",
            unit="1"
        )

    def _get_active_2pc_transactions_count(self, options):
        with self.transactions_lock:
            count = len([tx for tx in self.active_2pc_transactions.values() if tx["state"] == "PREPARED"])
            yield Measurement(count, {"node_id": self.node_id}, self.active_2pc_transactions_gauge, context.get_current())

    def _is_leader(self):
        return self.raft_node.state == LEADER

    def GetNodeRole(self, request, context):
        with self.raft_node.lock:
            return books_database_pb2.GetNodeRoleResponse(
                node_id=self.node_id,
                role=self.raft_node.state,
                term=self.raft_node.current_term,
                leader_id=self.raft_node.leader_id or ""
            )

    # --- Raft RPC implementations ---
    def RequestVote(self, request, context):
        term, vote_granted = self.raft_node.handle_request_vote(request.term, request.candidate_id)
        return books_database_pb2.DBVoteResponse(term=term, vote_granted=vote_granted)

    def AppendEntries(self, request, context): # Simplified for heartbeat
        term, success = self.raft_node.handle_append_entries(request.term, request.leader_id)
        return books_database_pb2.DBAppendEntriesResponse(term=term, success=success)

    # --- Data operations ---
    def ReadStock(self, request, context):
        with tracer.start_as_current_span("ReadStock") as span:
            span.set_attribute("book.id", request.book_id)
            start_time = time.time()
            logger.info(f"[{self.node_id}] ReadStock request for {request.book_id}")
            if not self._is_leader():
                leader_id = self.raft_node.leader_id
                msg = f"Not the leader. Current leader might be {leader_id}."
                logger.warning(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                context.abort(grpc.StatusCode.UNAVAILABLE, msg)

            with self.key_locks[request.book_id]:
                if request.book_id in self.datastore:
                    qty = self.datastore[request.book_id]
                    logger.info(f"[{self.node_id}] ReadStock success for {request.book_id}: {qty}")
                    books_read_counter.add(1, {"book_id": request.book_id, "node_id": self.node_id})
                    read_stock_latency_histogram.record(time.time() - start_time, {"book_id": request.book_id, "node_id": self.node_id})
                    return books_database_pb2.ReadStockResponse(
                        book_id=request.book_id, quantity=qty, success=True, message="Success"
                    )
                else:
                    logger.warning(f"[{self.node_id}] ReadStock failed for {request.book_id}: Not found")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Book not found"))
                    read_stock_latency_histogram.record(time.time() - start_time, {"book_id": request.book_id, "node_id": self.node_id})
                    return books_database_pb2.ReadStockResponse(
                        book_id=request.book_id, success=False, message="Book not found"
                    )

    def WriteStock(self, request, context):
        with tracer.start_as_current_span("WriteStock") as span:
            span.set_attribute("book.id", request.book_id)
            span.set_attribute("quantity.new", request.quantity)
            logger.info(f"[{self.node_id}] WriteStock request for {request.book_id} to {request.quantity}")
            if not self._is_leader():
                leader_id = self.raft_node.leader_id
                msg = f"Not the leader. Current leader might be {leader_id}."
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                context.abort(grpc.StatusCode.UNAVAILABLE, msg)

            op_id = str(uuid.uuid4())
            success_replication = False
            with self.key_locks[request.book_id]:
                original_quantity = self.datastore.get(request.book_id, None)
                self.datastore[request.book_id] = request.quantity
                logger.info(f"[{self.node_id}] Locally updated {request.book_id} to {request.quantity}")
                
                success_replication = self._replicate_to_backups(request.book_id, request.quantity, op_id)
                if not success_replication:
                    if original_quantity is not None:
                        self.datastore[request.book_id] = original_quantity
                    else:
                        del self.datastore[request.book_id]
                    logger.error(f"[{self.node_id}] Replication failed for WriteStock on {request.book_id}. Rolled back.")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Replication to backups failed"))
                    return books_database_pb2.WriteStockResponse(success=False, message="Replication to backups failed")
                
                # Update UpDownCounter after successful write/replication
                if original_quantity is None: # New book added
                    books_in_stock_updowncounter.add(request.quantity, {"book_id": request.book_id, "node_id": self.node_id})
                else:
                    books_in_stock_updowncounter.add(request.quantity - original_quantity, {"book_id": request.book_id, "node_id": self.node_id})

            logger.info(f"[{self.node_id}] WriteStock success and replicated for {request.book_id}")
            return books_database_pb2.WriteStockResponse(success=True, message="Stock updated and replicated")


    def DecrementStock(self, request, context):
        with tracer.start_as_current_span("DecrementStock") as span:
            span.set_attribute("book.id", request.book_id)
            span.set_attribute("amount.decrement", request.amount_to_decrement)
            logger.info(f"[{self.node_id}] DecrementStock request for {request.book_id} by {request.amount_to_decrement}")
            if not self._is_leader():
                leader_id = self.raft_node.leader_id
                msg = f"Not the leader. Current leader might be {leader_id}."
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                context.abort(grpc.StatusCode.UNAVAILABLE, msg)

            op_id = str(uuid.uuid4())
            new_quantity = -1
            success_replication = False

            with self.key_locks[request.book_id]:
                if request.book_id not in self.datastore:
                    logger.warning(f"[{self.node_id}] DecrementStock failed: {request.book_id} not found.")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Book not found"))
                    return books_database_pb2.DecrementStockResponse(
                        book_id=request.book_id, success=False, message="Book not found"
                    )

                current_quantity = self.datastore[request.book_id]
                if current_quantity < request.amount_to_decrement:
                    logger.warning(f"[{self.node_id}] DecrementStock failed: Insufficient stock for {request.book_id}. Has {current_quantity}, needs {request.amount_to_decrement}")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Insufficient stock"))
                    return books_database_pb2.DecrementStockResponse(
                        book_id=request.book_id, new_quantity=current_quantity, success=False, message="Insufficient stock"
                    )

                new_quantity = current_quantity - request.amount_to_decrement
                self.datastore[request.book_id] = new_quantity
                logger.info(f"[{self.node_id}] Locally decremented {request.book_id} to {new_quantity}")

                success_replication = self._replicate_to_backups(request.book_id, new_quantity, op_id)
                if not success_replication:
                    self.datastore[request.book_id] = current_quantity 
                    logger.error(f"[{self.node_id}] Replication failed for {request.book_id}. Rolled back decrement.")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Replication to backups failed"))
                    return books_database_pb2.DecrementStockResponse(
                        book_id=request.book_id, new_quantity=current_quantity, success=False, message="Replication to backups failed"
                    )
                
                books_in_stock_updowncounter.add(-request.amount_to_decrement, {"book_id": request.book_id, "node_id": self.node_id})

            logger.info(f"[{self.node_id}] DecrementStock success and replicated for {request.book_id}. New quantity: {new_quantity}")
            return books_database_pb2.DecrementStockResponse(
                book_id=request.book_id, new_quantity=new_quantity, success=True, message="Stock decremented and replicated"
            )


    def IncrementStock(self, request, context):
        with tracer.start_as_current_span("IncrementStock") as span:
            span.set_attribute("book.id", request.book_id)
            span.set_attribute("amount.increment", request.amount_to_increment)
            logger.info(f"[{self.node_id}] IncrementStock request for {request.book_id} by {request.amount_to_increment}")
            if not self._is_leader():
                leader_id = self.raft_node.leader_id
                msg = f"Not the leader. Current leader might be {leader_id}."
                logger.warning(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                context.abort(grpc.StatusCode.UNAVAILABLE, msg)

            if request.amount_to_increment <= 0:
                logger.warning(f"[{self.node_id}] IncrementStock failed: amount_to_increment must be positive, got {request.amount_to_increment}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description="Amount to increment must be positive"))
                return books_database_pb2.IncrementStockResponse(
                    book_id=request.book_id, success=False, message="Amount to increment must be positive"
                )

            op_id = str(uuid.uuid4())
            new_quantity = -1

            with self.key_locks[request.book_id]:
                if request.book_id not in self.datastore:
                    logger.info(f"[{self.node_id}] Book {request.book_id} not found. Initializing stock before increment.")
                    self.datastore[request.book_id] = 0
                
                current_quantity = self.datastore[request.book_id]
                new_quantity = current_quantity + request.amount_to_increment
                self.datastore[request.book_id] = new_quantity
                logger.info(f"[{self.node_id}] Locally incremented {request.book_id} from {current_quantity} to {new_quantity}")

                success_replication = self._replicate_to_backups(request.book_id, new_quantity, op_id)
                if not success_replication:
                    self.datastore[request.book_id] = current_quantity 
                    logger.error(f"[{self.node_id}] Replication failed for IncrementStock on {request.book_id}. Rolled back increment.")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Replication to backups failed"))
                    return books_database_pb2.IncrementStockResponse(
                        book_id=request.book_id, new_quantity=current_quantity, success=False, message="Replication to backups failed"
                    )
                
                books_in_stock_updowncounter.add(request.amount_to_increment, {"book_id": request.book_id, "node_id": self.node_id})

            logger.info(f"[{self.node_id}] IncrementStock success and replicated for {request.book_id}. New quantity: {new_quantity}")
            return books_database_pb2.IncrementStockResponse(
                book_id=request.book_id, new_quantity=new_quantity, success=True, message="Stock incremented and replicated"
            )
    
    def _replicate_to_backups(self, book_id, new_quantity, operation_id):
        with tracer.start_as_current_span("ReplicateToBackups") as span:
            span.set_attribute("book.id", book_id)
            span.set_attribute("quantity.new", new_quantity)
            span.set_attribute("operation.id", operation_id)

            if not self.peer_addresses:
                logger.info(f"[{self.node_id}] No peers to replicate to. Operation considered successful.")
                return True

            num_peers = len(self.peer_addresses)
            quorum_size = (num_peers + 1) // 2 + 1
            acks_needed_from_backups = quorum_size -1
            
            if acks_needed_from_backups <= 0:
                 logger.info(f"[{self.node_id}] Quorum met by leader alone or with one backup where leader's ack is enough. Op_id: {operation_id}")
                 return True


            replication_event = threading.Event()
            with self.replication_lock:
                self.pending_replications[operation_id] = {
                    "acks_received": 0,
                    "event": replication_event,
                    "start_time": time.time()
                }

            logger.info(f"[{self.node_id}] Replicating op_id {operation_id} for {book_id} to {new_quantity}. Need {acks_needed_from_backups} acks from {num_peers} peers.")
            span.set_attribute("replication.acks_needed", acks_needed_from_backups)

            for peer_addr in self.peer_addresses:
                threading.Thread(target=self._send_internal_replicate_to_peer, 
                                 args=(peer_addr, book_id, new_quantity, operation_id)).start()
            
            success = replication_event.wait(timeout=2.0) 

            with self.replication_lock:
                details = self.pending_replications.pop(operation_id, None)

            if success:
                logger.info(f"[{self.node_id}] Replication successful for op_id {operation_id}. Acks: {details['acks_received'] if details else 'N/A'}")
                return True
            else:
                logger.error(f"[{self.node_id}] Replication timed out or failed for op_id {operation_id}. Acks: {details['acks_received'] if details else 'N/A'}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description="Replication timed out or failed"))
                return False


    def _send_internal_replicate_to_peer(self, peer_addr, book_id, new_quantity, operation_id):
        with tracer.start_as_current_span("SendInternalReplicateToPeer") as span:
            span.set_attribute("peer.address", peer_addr)
            span.set_attribute("book.id", book_id)
            span.set_attribute("operation.id", operation_id)
            try:
                with grpc.insecure_channel(peer_addr) as channel:
                    stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                    req = books_database_pb2.InternalReplicateRequest(
                        book_id=book_id, new_quantity=new_quantity, operation_id=operation_id
                    )
                    logger.debug(f"[{self.node_id}] Sending InternalReplicate to {peer_addr} for op {operation_id}")
                    resp = stub.InternalReplicate(req, timeout=1.0)

                    if resp.success:
                        with self.replication_lock:
                            if operation_id in self.pending_replications:
                                self.pending_replications[operation_id]["acks_received"] += 1
                                logger.info(f"[{self.node_id}] ACK for op {operation_id} from {resp.node_id}. Total acks: {self.pending_replications[operation_id]['acks_received']}")
                                
                                num_peers = len(self.peer_addresses)
                                quorum_size = (num_peers + 1) // 2 + 1
                                acks_needed_from_backups = quorum_size -1
                                if acks_needed_from_backups <=0 : acks_needed_from_backups = 0

                                if self.pending_replications[operation_id]["acks_received"] >= acks_needed_from_backups:
                                    self.pending_replications[operation_id]["event"].set()
                    else:
                        span.set_status(trace.Status(trace.StatusCode.ERROR, description="InternalReplicate failed on peer"))
            except Exception as e:
                logger.error(f"[{self.node_id}] Failed to send InternalReplicate to {peer_addr} for op {operation_id}: {e}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=f"RPC failed: {e}"))


    def InternalReplicate(self, request, context):
        with tracer.start_as_current_span("InternalReplicate") as span:
            span.set_attribute("book.id", request.book_id)
            span.set_attribute("quantity.new", request.new_quantity)
            span.set_attribute("operation.id", request.operation_id)
            logger.info(f"[{self.node_id}] Received InternalReplicate for {request.book_id} to {request.new_quantity} (op: {request.operation_id})")
            with self.key_locks[request.book_id]:
                self.datastore[request.book_id] = request.new_quantity
                books_in_stock_updowncounter.set(self.datastore[request.book_id], {"book_id": request.book_id, "node_id": self.node_id})
            logger.info(f"[{self.node_id}] Applied replicated data for {request.book_id}. New quantity: {self.datastore[request.book_id]}")
            return books_database_pb2.InternalReplicateResponse(success=True, node_id=self.node_id)

    # --- 2PC Transaction Methods ---
    def PrepareTransaction(self, request, context):
        with tracer.start_as_current_span("PrepareTransaction") as span:
            transaction_id = request.transaction_id
            span.set_attribute("transaction.id", transaction_id)
            logger.info(f"[{self.node_id}] PrepareTransaction received for TX_ID: {transaction_id}")

            if not self._is_leader():
                leader_id = self.raft_node.leader_id
                msg = f"Not the leader. Current leader for DB Raft group might be {leader_id}."
                logger.warning(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                return books_database_pb2.DBVoteTransactionResponse(
                    transaction_id=transaction_id,
                    vote=books_database_pb2.DB_VOTE_ABORT,
                    message=msg
                )

            with self.transactions_lock:
                if transaction_id in self.active_2pc_transactions:
                    if self.active_2pc_transactions[transaction_id]["state"] == "PREPARED":
                         logger.warning(f"[{self.node_id}] TX_ID: {transaction_id} already prepared. Voting COMMIT again.")
                         span.set_attribute("transaction.state", "PREPARED")
                         return books_database_pb2.DBVoteTransactionResponse(transaction_id=transaction_id, vote=books_database_pb2.DB_VOTE_COMMIT, message="Already prepared")
                    else:
                         logger.error(f"[{self.node_id}] TX_ID: {transaction_id} in terminal state {self.active_2pc_transactions[transaction_id]['state']}. Voting ABORT.")
                         span.set_status(trace.Status(trace.StatusCode.ERROR, description="Transaction in terminal state"))
                         return books_database_pb2.DBVoteTransactionResponse(transaction_id=transaction_id, vote=books_database_pb2.DB_VOTE_ABORT, message="Transaction in terminal state")

                for op in request.operations:
                    with self.key_locks[op.book_id]:
                        current_quantity = self.datastore.get(op.book_id, None)
                        if current_quantity is None:
                            logger.warning(f"[{self.node_id}] TX_ID: {transaction_id} Prepare ABORT: Book {op.book_id} not found.")
                            span.set_status(trace.Status(trace.StatusCode.ERROR, description=f"Book {op.book_id} not found"))
                            return books_database_pb2.DBVoteTransactionResponse(transaction_id=transaction_id, vote=books_database_pb2.DB_VOTE_ABORT, message=f"Book {op.book_id} not found")
                        
                        if op.quantity_change < 0:
                            if current_quantity < abs(op.quantity_change):
                                logger.warning(f"[{self.node_id}] TX_ID: {transaction_id} Prepare ABORT: Insufficient stock for {op.book_id}. Has {current_quantity}, needs {abs(op.quantity_change)}")
                                span.set_status(trace.Status(trace.StatusCode.ERROR, description=f"Insufficient stock for {op.book_id}"))
                                return books_database_pb2.DBVoteTransactionResponse(transaction_id=transaction_id, vote=books_database_pb2.DB_VOTE_ABORT, message=f"Insufficient stock for {op.book_id}")

                self.active_2pc_transactions[transaction_id] = {
                    "state": "PREPARED",
                    "operations": request.operations
                }
                logger.info(f"[{self.node_id}] TX_ID: {transaction_id} PREPARED. Voting COMMIT.")
                span.set_attribute("transaction.state", "PREPARED")
                return books_database_pb2.DBVoteTransactionResponse(transaction_id=transaction_id, vote=books_database_pb2.DB_VOTE_COMMIT, message="Prepared successfully")

    def CommitTransaction(self, request, context):
        with tracer.start_as_current_span("CommitTransaction") as span:
            transaction_id = request.transaction_id
            span.set_attribute("transaction.id", transaction_id)
            logger.info(f"[{self.node_id}] CommitTransaction received for TX_ID: {transaction_id}")

            if not self._is_leader():
                msg = "Not the leader. Cannot process Commit."
                logger.error(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
                span.set_status(trace.Status(trace.StatusCode.ERROR, description=msg))
                return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_FAILURE, message=msg)

            with self.transactions_lock:
                if transaction_id not in self.active_2pc_transactions or self.active_2pc_transactions[transaction_id]["state"] != "PREPARED":
                    current_state = self.active_2pc_transactions.get(transaction_id, {}).get("state", "NOT_FOUND")
                    logger.error(f"[{self.node_id}] TX_ID: {transaction_id} Cannot Commit. State: {current_state}")
                    if current_state == "COMMITTED":
                        span.set_attribute("transaction.state", "COMMITTED")
                        return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message="Transaction already committed")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description=f"Transaction not in PREPARED state (state: {current_state})"))
                    return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_FAILURE, message=f"Transaction not in PREPARED state (state: {current_state})")

                staged_operations = self.active_2pc_transactions[transaction_id]["operations"]
                
                all_ops_replicated = True
                applied_ops_details = []

                for op in staged_operations:
                    book_id = op.book_id
                    quantity_change = op.quantity_change
                    
                    with self.key_locks[book_id]:
                        current_quantity = self.datastore.get(book_id, 0)
                        new_quantity = current_quantity + quantity_change
                        
                        original_book_quantity_for_rollback = self.datastore[book_id]
                        self.datastore[book_id] = new_quantity
                        
                        replication_op_id = f"{transaction_id}_{book_id}"
                        logger.info(f"[{self.node_id}] TX_ID: {transaction_id} - Committing op for {book_id}: {current_quantity} -> {new_quantity}. Replicating (op_id: {replication_op_id})...")
                        
                        if not self._replicate_to_backups(book_id, new_quantity, replication_op_id):
                            logger.error(f"[{self.node_id}] TX_ID: {transaction_id} - FAILED to replicate change for {book_id}. Rolling back this operation.")
                            self.datastore[book_id] = original_book_quantity_for_rollback
                            all_ops_replicated = False
                            break 
                        else:
                            applied_ops_details.append({"book_id": book_id, "old_qty": original_book_quantity_for_rollback, "new_qty": new_quantity})
                            logger.info(f"[{self.node_id}] TX_ID: {transaction_id} - Successfully applied and replicated for {book_id}.")
                            books_in_stock_updowncounter.add(quantity_change, {"book_id": book_id, "node_id": self.node_id})


                if all_ops_replicated:
                    self.active_2pc_transactions[transaction_id]["state"] = "COMMITTED"
                    logger.info(f"[{self.node_id}] TX_ID: {transaction_id} COMMITTED successfully.")
                    span.set_attribute("transaction.state", "COMMITTED")
                    return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message="Transaction committed and replicated")
                else:
                    logger.error(f"[{self.node_id}] TX_ID: {transaction_id} - Commit FAILED due to replication issue. Attempting to rollback locally applied changes for this TX.")
                    for detail in reversed(applied_ops_details):
                        with self.key_locks[detail["book_id"]]:
                            self.datastore[detail["book_id"]] = detail["old_qty"]
                    self.active_2pc_transactions[transaction_id]["state"] = "ABORTED"
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Commit failed due to replication failure"))
                    return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_FAILURE, message="Commit failed due to replication failure of one or more operations")

    def AbortTransaction(self, request, context):
        with tracer.start_as_current_span("AbortTransaction") as span:
            transaction_id = request.transaction_id
            span.set_attribute("transaction.id", transaction_id)
            logger.info(f"[{self.node_id}] AbortTransaction received for TX_ID: {transaction_id}")

            if not self._is_leader():
                msg = "Not the leader, but acknowledging Abort."
                logger.warning(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
                return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message=msg)

            with self.transactions_lock:
                tx_info = self.active_2pc_transactions.get(transaction_id)
                if not tx_info:
                    logger.warning(f"[{self.node_id}] TX_ID: {transaction_id} not found for Abort. Assuming already handled or never prepared.")
                    return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message="Transaction not found, abort acknowledged")

                if tx_info["state"] == "COMMITTED":
                    logger.error(f"[{self.node_id}] TX_ID: {transaction_id} CRITICAL: Received Abort for already COMMITTED transaction.")
                    span.set_status(trace.Status(trace.StatusCode.ERROR, description="Received Abort for already COMMITTED transaction"))
                    return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_FAILURE, message="Transaction already committed, cannot abort")
                
                if tx_info["state"] == "ABORTED":
                     logger.info(f"[{self.node_id}] TX_ID: {transaction_id} already ABORTED. Acknowledging abort again.")
                     span.set_attribute("transaction.state", "ABORTED")
                     return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message="Transaction already aborted")

                tx_info["state"] = "ABORTED"
                logger.info(f"[{self.node_id}] TX_ID: {transaction_id} ABORTED.")
                span.set_attribute("transaction.state", "ABORTED")
                return books_database_pb2.DBAckTransactionResponse(transaction_id=transaction_id, status=books_database_pb2.DB_ACK_SUCCESS, message="Transaction aborted successfully")

def serve():
    db_node_port = os.environ.get("DB_NODE_PORT", "50060") # Default port
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    books_database_pb2_grpc.add_BooksDatabaseServiceServicer_to_server(BooksDatabaseServiceServicer(), server)
    server.add_insecure_port(f"[::]:{db_node_port}")
    logger.info(f"Books Database Service node [{os.environ.get('DB_NODE_ID', 'unknown')}] started on port {db_node_port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
