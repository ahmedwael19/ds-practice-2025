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

# --- Protobuf Imports ---
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
books_database_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/books_database'))
sys.path.insert(0, books_database_grpc_path)

import books_database_pb2
import books_database_pb2_grpc

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("books_database")

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
        self.key_locks = defaultdict(threading.Lock)
        self.pending_replications = {} # op_id -> {count, event, start_time}
        self.replication_lock = threading.Lock()

        logger.info(f"[{self.node_id}] BooksDatabaseService initialized. Datastore: {self.datastore}")
        self.raft_node.start()

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
        logger.info(f"[{self.node_id}] ReadStock request for {request.book_id}")
        if not self._is_leader():
            leader_id = self.raft_node.leader_id
            msg = f"Not the leader. Current leader might be {leader_id}."
            logger.warning(f"[{self.node_id}] {msg} Role: {self.raft_node.state}")
            context.abort(grpc.StatusCode.UNAVAILABLE, msg) # Client should retry with leader hint
            # return books_database_pb2.ReadStockResponse(success=False, message=msg)


        with self.key_locks[request.book_id]: # Reading also needs lock if there are concurrent writes that could change it
            if request.book_id in self.datastore:
                qty = self.datastore[request.book_id]
                logger.info(f"[{self.node_id}] ReadStock success for {request.book_id}: {qty}")
                return books_database_pb2.ReadStockResponse(
                    book_id=request.book_id, quantity=qty, success=True, message="Success"
                )
            else:
                logger.warning(f"[{self.node_id}] ReadStock failed for {request.book_id}: Not found")
                return books_database_pb2.ReadStockResponse(
                    book_id=request.book_id, success=False, message="Book not found"
                )

    def WriteStock(self, request, context):
        logger.info(f"[{self.node_id}] WriteStock request for {request.book_id} to {request.quantity}")
        if not self._is_leader():
            leader_id = self.raft_node.leader_id
            msg = f"Not the leader. Current leader might be {leader_id}."
            context.abort(grpc.StatusCode.UNAVAILABLE, msg)

        op_id = str(uuid.uuid4())
        success_replication = False
        with self.key_locks[request.book_id]:
            original_quantity = self.datastore.get(request.book_id, None)
            self.datastore[request.book_id] = request.quantity
            logger.info(f"[{self.node_id}] Locally updated {request.book_id} to {request.quantity}")
            
            success_replication = self._replicate_to_backups(request.book_id, request.quantity, op_id)
            if not success_replication:
                # Rollback local change if replication fails
                if original_quantity is not None:
                    self.datastore[request.book_id] = original_quantity
                else: # was a new book
                    del self.datastore[request.book_id]
                logger.error(f"[{self.node_id}] Replication failed for WriteStock on {request.book_id}. Rolled back.")
                return books_database_pb2.WriteStockResponse(success=False, message="Replication to backups failed")

        logger.info(f"[{self.node_id}] WriteStock success and replicated for {request.book_id}")
        return books_database_pb2.WriteStockResponse(success=True, message="Stock updated and replicated")


    def DecrementStock(self, request, context):
        logger.info(f"[{self.node_id}] DecrementStock request for {request.book_id} by {request.amount_to_decrement}")
        if not self._is_leader():
            leader_id = self.raft_node.leader_id
            msg = f"Not the leader. Current leader might be {leader_id}."
            context.abort(grpc.StatusCode.UNAVAILABLE, msg) # Client should retry

        op_id = str(uuid.uuid4())
        new_quantity = -1
        success_replication = False

        with self.key_locks[request.book_id]:
            if request.book_id not in self.datastore:
                logger.warning(f"[{self.node_id}] DecrementStock failed: {request.book_id} not found.")
                return books_database_pb2.DecrementStockResponse(
                    book_id=request.book_id, success=False, message="Book not found"
                )

            current_quantity = self.datastore[request.book_id]
            if current_quantity < request.amount_to_decrement:
                logger.warning(f"[{self.node_id}] DecrementStock failed: Insufficient stock for {request.book_id}. Has {current_quantity}, needs {request.amount_to_decrement}")
                return books_database_pb2.DecrementStockResponse(
                    book_id=request.book_id, new_quantity=current_quantity, success=False, message="Insufficient stock"
                )

            # Apply locally first
            new_quantity = current_quantity - request.amount_to_decrement
            self.datastore[request.book_id] = new_quantity
            logger.info(f"[{self.node_id}] Locally decremented {request.book_id} to {new_quantity}")

            # Replicate to backups
            success_replication = self._replicate_to_backups(request.book_id, new_quantity, op_id)
            if not success_replication:
                # Rollback local change
                self.datastore[request.book_id] = current_quantity 
                logger.error(f"[{self.node_id}] Replication failed for {request.book_id}. Rolled back decrement.")
                return books_database_pb2.DecrementStockResponse(
                    book_id=request.book_id, new_quantity=current_quantity, success=False, message="Replication to backups failed"
                )

        logger.info(f"[{self.node_id}] DecrementStock success and replicated for {request.book_id}. New quantity: {new_quantity}")
        return books_database_pb2.DecrementStockResponse(
            book_id=request.book_id, new_quantity=new_quantity, success=True, message="Stock decremented and replicated"
        )

    def _replicate_to_backups(self, book_id, new_quantity, operation_id):
        if not self.peer_addresses:
            logger.info(f"[{self.node_id}] No peers to replicate to. Operation considered successful.")
            return True # Standalone mode

        num_peers = len(self.peer_addresses)
        # Quorum includes the leader itself. So, leader + (num_peers / 2) for odd total, or leader + (num_peers / 2 -1) for even total if leader is first.
        # Simpler: majority of total nodes. Total nodes = num_peers + 1. Quorum = (num_peers + 1) // 2 + 1.
        # ACKs needed from backups = quorum_size - 1 (leader is one ack)
        quorum_size = (num_peers + 1) // 2 + 1
        acks_needed_from_backups = quorum_size -1
        
        if acks_needed_from_backups <= 0: # Only leader, or leader + 1 backup where leader is majority
             logger.info(f"[{self.node_id}] Quorum met by leader alone or with one backup where leader's ack is enough. Op_id: {operation_id}")
             return True


        replication_event = threading.Event()
        with self.replication_lock:
            self.pending_replications[operation_id] = {
                "acks_received": 0, # From backups
                "event": replication_event,
                "start_time": time.time()
            }

        logger.info(f"[{self.node_id}] Replicating op_id {operation_id} for {book_id} to {new_quantity}. Need {acks_needed_from_backups} acks from {num_peers} peers.")

        for peer_addr in self.peer_addresses:
            threading.Thread(target=self._send_internal_replicate_to_peer, 
                             args=(peer_addr, book_id, new_quantity, operation_id)).start()
        
        # Wait for quorum or timeout
        # Timeout should be less than client RPC timeout. E.g. 2 seconds.
        success = replication_event.wait(timeout=2.0) 

        with self.replication_lock:
            details = self.pending_replications.pop(operation_id, None) # Clean up

        if success:
            logger.info(f"[{self.node_id}] Replication successful for op_id {operation_id}. Acks: {details['acks_received'] if details else 'N/A'}")
            return True
        else:
            logger.error(f"[{self.node_id}] Replication timed out or failed for op_id {operation_id}. Acks: {details['acks_received'] if details else 'N/A'}")
            return False


    def _send_internal_replicate_to_peer(self, peer_addr, book_id, new_quantity, operation_id):
        try:
            with grpc.insecure_channel(peer_addr) as channel:
                stub = books_database_pb2_grpc.BooksDatabaseServiceStub(channel)
                req = books_database_pb2.InternalReplicateRequest(
                    book_id=book_id, new_quantity=new_quantity, operation_id=operation_id
                )
                logger.debug(f"[{self.node_id}] Sending InternalReplicate to {peer_addr} for op {operation_id}")
                resp = stub.InternalReplicate(req, timeout=1.0) # Short timeout for internal replication

                if resp.success:
                    with self.replication_lock:
                        if operation_id in self.pending_replications:
                            self.pending_replications[operation_id]["acks_received"] += 1
                            logger.info(f"[{self.node_id}] ACK for op {operation_id} from {resp.node_id}. Total acks: {self.pending_replications[operation_id]['acks_received']}")
                            
                            num_peers = len(self.peer_addresses)
                            quorum_size = (num_peers + 1) // 2 + 1
                            acks_needed_from_backups = quorum_size -1
                            if acks_needed_from_backups <=0 : acks_needed_from_backups = 0 # if only one node or two nodes

                            if self.pending_replications[operation_id]["acks_received"] >= acks_needed_from_backups:
                                self.pending_replications[operation_id]["event"].set()
        except Exception as e:
            logger.error(f"[{self.node_id}] Failed to send InternalReplicate to {peer_addr} for op {operation_id}: {e}")


    def InternalReplicate(self, request, context):
        # This is called on Backup nodes by the Primary
        logger.info(f"[{self.node_id}] Received InternalReplicate for {request.book_id} to {request.new_quantity} (op: {request.operation_id})")
        with self.key_locks[request.book_id]:
            self.datastore[request.book_id] = request.new_quantity
        logger.info(f"[{self.node_id}] Applied replicated data for {request.book_id}. New quantity: {self.datastore[request.book_id]}")
        return books_database_pb2.InternalReplicateResponse(success=True, node_id=self.node_id)


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