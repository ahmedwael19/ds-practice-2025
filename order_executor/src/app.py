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
import order_executor_pb2
import order_executor_pb2_grpc
import order_queue_pb2
import order_queue_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("order_executor")

# Get the executor instance ID from environment (set in docker-compose)
EXECUTOR_ID = os.environ.get("EXECUTOR_ID", str(uuid.uuid4())[:8])
QUEUE_SERVICE = os.environ.get("QUEUE_SERVICE", "order_queue:50054")

# Get all peer executor addresses from environment
# Format: "executor1:50055,executor2:50055,..."
PEERS_STR = os.environ.get("EXECUTOR_PEERS", "")
PEERS = [p for p in PEERS_STR.split(",") if p and p != f"order_executor_{EXECUTOR_ID}:50055"]

# Raft states
FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"

class RaftConsensus:
    def __init__(self, node_id, peers):
        self.node_id = node_id
        self.peers = peers
        self.state = FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.leader_id = None
        self.election_timeout = self._get_election_timeout()
        self.last_heartbeat = time.time()
        self.votes_received = 0
        self.processed_orders = 0
        
        # For thread safety
        self.lock = threading.RLock()
        
        # Processing flag to avoid multiple simultaneous order processing
        self.processing_order = False
        
        # Start election timer thread
        self.running = True
        self.election_timer = threading.Thread(target=self._run_election_timer)
        self.election_timer.daemon = True
        self.election_timer.start()
        
        # Start heartbeat timer if leader
        self.heartbeat_timer = None
        
        logger.info(f"Executor {self.node_id} initialized with peers: {self.peers}")
        
    def _get_election_timeout(self):
        # Random timeout between 1.5-3 seconds
        return random.uniform(1.5, 3.0)
        
    def _run_election_timer(self):
        while self.running:
            time.sleep(0.1)  # Check every 100ms
            
            with self.lock:
                if self.state == LEADER:
                    continue  # Leaders don't timeout
                    
                if time.time() - self.last_heartbeat > self.election_timeout:
                    # Timeout: convert to candidate and start election
                    logger.info(f"Election timeout reached, starting election")
                    self._start_election()
                    
    def _start_election(self):
        with self.lock:
            self.state = CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received = 1  # Vote for self
            self.election_timeout = self._get_election_timeout()
            self.last_heartbeat = time.time()
            
            logger.info(f"Starting election for term {self.current_term}")
            
            # Request votes from all peers
            for peer in self.peers:
                threading.Thread(target=self._request_vote, args=(peer,)).start()
                
    def _request_vote(self, peer_address):
        correlation_id = str(uuid.uuid4())
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                
                with self.lock:
                    if self.state != CANDIDATE:
                        return  # No longer a candidate
                        
                    request = order_executor_pb2.VoteRequest(
                        candidate_id=self.node_id,
                        term=self.current_term,
                        correlation_id=correlation_id
                    )
                
                logger.debug(f"[{correlation_id}] Requesting vote from {peer_address} for term {self.current_term}")
                response = stub.RequestVote(request, timeout=0.5)
                
                with self.lock:
                    if self.state != CANDIDATE or self.current_term != request.term:
                        return  # Term changed or no longer candidate
                        
                    if response.term > self.current_term:
                        # Found higher term, revert to follower
                        logger.info(f"[{correlation_id}] Discovered higher term {response.term}, reverting to follower")
                        self.state = FOLLOWER
                        self.current_term = response.term
                        self.voted_for = None
                        return
                        
                    if response.vote_granted:
                        logger.info(f"[{correlation_id}] Received vote from {peer_address}")
                        self.votes_received += 1
                        
                        # Check if we have majority of votes
                        if self.votes_received > (len(self.peers) + 1) / 2:
                            self._become_leader()
        except Exception as e:
            logger.error(f"[{correlation_id}] Error requesting vote from {peer_address}: {e}")
            
    def _become_leader(self):
        with self.lock:
            if self.state == CANDIDATE:
                self.state = LEADER
                self.leader_id = self.node_id
                logger.info(f"Node {self.node_id} became leader for term {self.current_term}")
                
                # Start sending heartbeats
                if self.heartbeat_timer is None:
                    self.heartbeat_timer = threading.Thread(target=self._send_heartbeats)
                    self.heartbeat_timer.daemon = True
                    self.heartbeat_timer.start()
                
                # Start the order processing loop
                threading.Thread(target=self._process_orders_loop).start()
                
    def _send_heartbeats(self):
        while self.running:
            time.sleep(0.5)  # Send heartbeats every 500ms
            
            with self.lock:
                if self.state != LEADER:
                    return  # No longer leader
                
                current_term = self.current_term
                
            correlation_id = str(uuid.uuid4())
            
            # Send heartbeats to all peers
            for peer_address in self.peers:
                threading.Thread(target=self._send_heartbeat, args=(peer_address, current_term, correlation_id)).start()
                    
    def _send_heartbeat(self, peer_address, term, correlation_id):
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = order_executor_pb2_grpc.OrderExecutorServiceStub(channel)
                
                request = order_executor_pb2.HeartbeatRequest(
                    leader_id=self.node_id,
                    term=term,
                    correlation_id=correlation_id
                )
                
                response = stub.Heartbeat(request, timeout=0.3)
                
                with self.lock:
                    if response.term > self.current_term:
                        # Found higher term, revert to follower
                        logger.info(f"[{correlation_id}] Discovered higher term {response.term} during heartbeat, reverting to follower")
                        self.state = FOLLOWER
                        self.current_term = response.term
                        self.voted_for = None
                        self.leader_id = None
        except Exception as e:
            # Don't log heartbeat errors as they're expected when nodes go down
            pass
            
    def _process_orders_loop(self):
        """Process orders from the queue while this node is the leader"""
        logger.info(f"Leader {self.node_id} starting order processing loop")
        
        while True:
            with self.lock:
                if self.state != LEADER:
                    logger.info(f"Node {self.node_id} is no longer leader, stopping order processing")
                    return
                
                # Only process one order at a time
                if self.processing_order:
                    time.sleep(0.5)
                    continue
                
                self.processing_order = True
            
            try:
                self._process_next_order()
            except Exception as e:
                logger.error(f"Error processing order: {e}")
            finally:
                with self.lock:
                    self.processing_order = False
            
            # Add a delay to avoid tight loop
            time.sleep(3.0)
            
    def _process_next_order(self):
        """Dequeue and process a single order"""
        correlation_id = str(uuid.uuid4())
        
        # First check if there are orders in the queue
        try:
            with grpc.insecure_channel(QUEUE_SERVICE) as channel:
                queue_stub = order_queue_pb2_grpc.OrderQueueServiceStub(channel)
                
                # Check queue status
                status_request = order_queue_pb2.QueueStatusRequest(executor_id=self.node_id)
                status_response = queue_stub.GetQueueStatus(status_request, metadata=(("correlation-id", correlation_id),))
                
                if not status_response.has_pending_orders:
                    # No orders to process
                    return
                
                # Dequeue an order
                dequeue_request = order_queue_pb2.DequeueRequest(executor_id=self.node_id)
                dequeue_response = queue_stub.DequeueOrder(dequeue_request, metadata=(("correlation-id", correlation_id),))
                
                if not dequeue_response.success:
                    logger.info(f"[{correlation_id}] No order to dequeue: {dequeue_response.message}")
                    return
                
                # Process the order
                order_id = dequeue_response.order_id
                order_data = dequeue_response.order_data
                
                logger.info(f"[{correlation_id}] Processing order {order_id}")
                
                # Simulate order processing
                logger.info(f"[{correlation_id}] Order {order_id} is being executed...")
                
                # Actual processing logic would go here:
                # - Update inventory
                # - Commit order to database
                # - Process payment
                # - Trigger notifications
                
                # Simulate processing time
                time.sleep(1.0)
                
                logger.info(f"[{correlation_id}] Order {order_id} execution completed successfully")
                
                with self.lock:
                    self.processed_orders += 1
        
        except Exception as e:
            logger.error(f"[{correlation_id}] Error processing order: {e}")
            raise

class OrderExecutorServicer(order_executor_pb2_grpc.OrderExecutorServiceServicer):
    def __init__(self, consensus):
        self.consensus = consensus
        
    def RequestVote(self, request, context):
        correlation_id = request.correlation_id
        candidate_id = request.candidate_id
        term = request.term
        
        logger.info(f"[{correlation_id}] Received vote request from {candidate_id} for term {term}")
        
        with self.consensus.lock:
            # If the candidate's term is outdated, reject vote
            if term < self.consensus.current_term:
                logger.info(f"[{correlation_id}] Rejecting vote: candidate term {term} < current term {self.consensus.current_term}")
                return order_executor_pb2.VoteResponse(vote_granted=False, term=self.consensus.current_term)
                
            # If we discover a higher term, update our term and become follower
            if term > self.consensus.current_term:
                logger.info(f"[{correlation_id}] Discovered higher term {term}, updating term and becoming follower")
                self.consensus.current_term = term
                self.consensus.state = FOLLOWER
                self.consensus.voted_for = None
                
            # If we haven't voted yet in this term or already voted for this candidate
            if (self.consensus.voted_for is None or self.consensus.voted_for == candidate_id) and term >= self.consensus.current_term:
                logger.info(f"[{correlation_id}] Granting vote to {candidate_id} for term {term}")
                self.consensus.voted_for = candidate_id
                self.consensus.last_heartbeat = time.time()  # Reset election timeout
                return order_executor_pb2.VoteResponse(vote_granted=True, term=self.consensus.current_term)
                
            # Otherwise reject vote
            logger.info(f"[{correlation_id}] Rejecting vote: already voted for {self.consensus.voted_for}")
            return order_executor_pb2.VoteResponse(vote_granted=False, term=self.consensus.current_term)
            
    def Heartbeat(self, request, context):
        leader_id = request.leader_id
        term = request.term
        
        with self.consensus.lock:
            # If leader's term is outdated, reject heartbeat
            if term < self.consensus.current_term:
                return order_executor_pb2.HeartbeatResponse(success=False, term=self.consensus.current_term)
                
            # If we discover a higher term, update our term
            if term > self.consensus.current_term:
                self.consensus.current_term = term
                
            # Accept valid heartbeat, reset timeout
            self.consensus.last_heartbeat = time.time()
            self.consensus.state = FOLLOWER
            self.consensus.leader_id = leader_id
            
            return order_executor_pb2.HeartbeatResponse(success=True, term=self.consensus.current_term)
            
    def GetExecutorStatus(self, request, context):
        correlation_id = request.correlation_id
        logger.info(f"[{correlation_id}] Status request received")
        
        with self.consensus.lock:
            return order_executor_pb2.StatusResponse(
                executor_id=self.consensus.node_id,
                state=self.consensus.state,
                current_term=self.consensus.current_term,
                processed_orders=self.consensus.processed_orders,
                leader_id=self.consensus.leader_id or ""
            )

def serve():
    # Initialize Raft consensus algorithm
    consensus = RaftConsensus(node_id=EXECUTOR_ID, peers=PEERS)
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    order_executor_pb2_grpc.add_OrderExecutorServiceServicer_to_server(OrderExecutorServicer(consensus), server)
    server.add_insecure_port('[::]:50055')  # Using port 50055 for the executor service
    server.start()
    logger.info(f"Order Executor {EXECUTOR_ID} started on port 50055")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()