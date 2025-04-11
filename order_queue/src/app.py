import time
import grpc
import logging
import uuid
import heapq
import json
from concurrent import futures
from threading import Lock
import os
# Import generated gRPC code
import sys
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")

order_queue_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/order_queue'))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2
import order_queue_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("order_queue")

class PriorityOrderQueue:
    def __init__(self):
        self.queue = []  # Priority queue using heapq
        self.lock = Lock()  # For thread safety
        self.order_data = {}  # Store order data by ID
        
    def enqueue(self, order_id, order_data, vector_clock):
        with self.lock:
            # Calculate priority based on order data
            priority = self._calculate_priority(order_data)
            
            # Store order data
            self.order_data[order_id] = {
                "data": order_data,
                "vector_clock": vector_clock
            }
            
            # Push to priority queue
            heapq.heappush(self.queue, (priority, order_id))
            
            logger.info(f"Enqueued order {order_id} with priority {priority}, queue size: {len(self.queue)}")
            return True
            
    def dequeue(self):
        with self.lock:
            if not self.queue:
                return None, None, None
                
            # Get highest priority order
            _, order_id = heapq.heappop(self.queue)
            
            # Get order data
            if order_id not in self.order_data:
                logger.error(f"Order {order_id} not found in order_data")
                return None, None, None
                
            order_info = self.order_data.pop(order_id)
            
            logger.info(f"Dequeued order {order_id}, remaining queue size: {len(self.queue)}")
            return order_id, order_info["data"], order_info["vector_clock"]
            
    def size(self):
        with self.lock:
            return len(self.queue)
            
    def _calculate_priority(self, order_data):
        """
        Calculate priority based on order data
        Lower number = higher priority
        """
        priority = 0
        
        # Priority based on item quantity
        total_items = sum(item.quantity for item in order_data.items)
        if total_items > 10:
            priority -= 30  # Large orders get higher priority
        elif total_items > 5:
            priority -= 20
        elif total_items > 2:
            priority -= 10
        
        # Priority based on shipping method
        if order_data.shipping_method == "express":
            priority -= 25  # Express shipments get higher priority
        elif order_data.shipping_method == "priority":
            priority -= 15
            
        # Gift wrapping adds priority
        if order_data.gift_wrapping:
            priority -= 10
            
        # Add some randomness to avoid starvation of lower priority orders
        # This will gradually increase priority of older orders
        priority -= int(time.time() % 100) / 100
        
        return priority

class OrderQueueServicer(order_queue_pb2_grpc.OrderQueueServiceServicer):
    def __init__(self):
        self.queue = PriorityOrderQueue()
        
    def EnqueueOrder(self, request, context):
        correlation_id = dict(context.invocation_metadata()).get('correlation-id', str(uuid.uuid4()))
        logger.info(f"[{correlation_id}] Received EnqueueOrder request for order {request.order_id}")
        
        vector_clock = {k: v for k, v in request.vector_clock.items()}
        
        success = self.queue.enqueue(request.order_id, request.order_data, vector_clock)
        
        return order_queue_pb2.EnqueueResponse(
            success=success,
            message="Order successfully enqueued" if success else "Failed to enqueue order"
        )
        
    def DequeueOrder(self, request, context):
        correlation_id = dict(context.invocation_metadata()).get('correlation-id', str(uuid.uuid4()))
        executor_id = request.executor_id
        logger.info(f"[{correlation_id}] Executor {executor_id} attempting to dequeue an order")
        
        order_id, order_data, vector_clock = self.queue.dequeue()
        
        if order_id is None:
            return order_queue_pb2.DequeueResponse(
                success=False,
                message="Queue is empty",
                order_id="",
                order_data=None
            )
            
        response = order_queue_pb2.DequeueResponse(
            success=True,
            message=f"Order {order_id} dequeued for executor {executor_id}",
            order_id=order_id,
            order_data=order_data
        )
        
        # Add vector clock to response
        if vector_clock:
            for service, time in vector_clock.items():
                response.vector_clock[service] = time
        
        return response
        
    def GetQueueStatus(self, request, context):
        correlation_id = dict(context.invocation_metadata()).get('correlation-id', str(uuid.uuid4()))
        logger.info(f"[{correlation_id}] Received GetQueueStatus request from {request.executor_id}")
        
        queue_size = self.queue.size()
        return order_queue_pb2.QueueStatusResponse(
            has_pending_orders=queue_size > 0,
            queue_size=queue_size
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    order_queue_pb2_grpc.add_OrderQueueServiceServicer_to_server(OrderQueueServicer(), server)
    server.add_insecure_port('[::]:50054')  # Using port 50054 for the queue service
    server.start()
    logger.info("Order Queue service started on port 50054")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()