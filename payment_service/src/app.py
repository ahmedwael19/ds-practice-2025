import grpc
import time
import logging
from concurrent import futures
import sys
import os

# Add project root to sys.path to locate the 'utils' package
# Assumes app.py is at /usr/src/app/src/app.py and utils is at /usr/src/app/utils/
# __file__ is src/app.py. dirname(__file__) is src. join(dirname, '..') is /usr/src/app
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
payment_service_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/payment_service'))
sys.path.insert(0, payment_service_grpc_path)

# Now imports from 'utils' should work
import payment_service_pb2
import payment_service_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# In-memory store for transaction states
# Structure: {transaction_id: {"state": "PREPARED" | "COMMITTED" | "ABORTED", "details": ...}}
transactions = {}

class PaymentServiceServicer(payment_service_pb2_grpc.PaymentServiceServicer):
    def Prepare(self, request, context):
        transaction_id = request.transaction_id
        order_id = request.order_id
        amount = request.amount
        logging.info(f"Prepare received for transaction_id: {transaction_id}, order_id: {order_id}, amount: {amount}")

        # Dummy validation/preparation logic
        # For now, always assume preparation is successful
        if transaction_id in transactions and transactions[transaction_id]["state"] != "ABORTED":
            # If already prepared or committed, this might be a retry or an issue.
            # For simplicity, if prepared, vote commit again. If committed, it's an issue.
            if transactions[transaction_id]["state"] == "PREPARED":
                logging.warning(f"Transaction {transaction_id} already prepared. Voting COMMIT again.")
                return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_COMMIT, message="Already prepared")
            elif transactions[transaction_id]["state"] == "COMMITTED":
                 logging.error(f"Transaction {transaction_id} already committed. Cannot prepare again. Voting ABORT.")
                 # This scenario should ideally not happen if coordinator logic is correct.
                 return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_ABORT, message="Transaction already committed")

        # Simulate some work/check
        time.sleep(0.1) # Simulate I/O or processing

        transactions[transaction_id] = {
            "state": "PREPARED",
            "details": {"order_id": order_id, "amount": amount}
        }
        logging.info(f"Transaction {transaction_id} PREPARED. Voting COMMIT.")
        return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_COMMIT, message="Payment prepared successfully")

    def Commit(self, request, context):
        transaction_id = request.transaction_id
        logging.info(f"Commit received for transaction_id: {transaction_id}")

        if transaction_id not in transactions or transactions[transaction_id]["state"] != "PREPARED":
            logging.error(f"Cannot commit transaction {transaction_id}. State: {transactions.get(transaction_id, {}).get('state', 'NOT_FOUND')}")
            # This could happen if Prepare was not called, or if it was already aborted/committed.
            # Or if the coordinator decided to abort but somehow sent a commit.
            # Responding with failure, coordinator should handle this.
            return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_FAILURE, message="Transaction not in PREPARED state or not found")

        # Simulate dummy payment execution
        logging.info(f"Executing dummy payment for transaction_id: {transaction_id}, details: {transactions[transaction_id]['details']}")
        time.sleep(0.2) # Simulate payment processing

        transactions[transaction_id]["state"] = "COMMITTED"
        logging.info(f"Transaction {transaction_id} COMMITTED.")
        return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Payment committed successfully")

    def Abort(self, request, context):
        transaction_id = request.transaction_id
        logging.info(f"Abort received for transaction_id: {transaction_id}")

        if transaction_id not in transactions:
            logging.warning(f"Transaction {transaction_id} not found for Abort. Assuming already handled or never prepared.")
            # If not found, it might mean Prepare never reached or it was already cleaned up.
            # Acknowledging abort is safe.
            return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Transaction not found, abort acknowledged")

        current_state = transactions[transaction_id]["state"]
        if current_state == "COMMITTED":
            logging.error(f"CRITICAL: Received Abort for already COMMITTED transaction {transaction_id}. This indicates a serious issue in the 2PC protocol or coordinator logic.")
            # This is a problematic state. The transaction is already committed.
            # Cannot truly abort. Return failure to signal the problem.
            return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_FAILURE, message="Transaction already committed, cannot abort")
        
        if current_state == "ABORTED":
            logging.info(f"Transaction {transaction_id} already ABORTED. Acknowledging abort again.")
            return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Transaction already aborted")

        # For PREPARED or any other state (e.g. PENDING if we had one)
        logging.info(f"Aborting transaction_id: {transaction_id}. Releasing resources (dummy).")
        # Simulate releasing any locked resources or reversing prepared actions
        time.sleep(0.1)

        transactions[transaction_id]["state"] = "ABORTED"
        logging.info(f"Transaction {transaction_id} ABORTED.")
        return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Payment aborted successfully")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    payment_service_pb2_grpc.add_PaymentServiceServicer_to_server(PaymentServiceServicer(), server)
    
    port = "50057" # Assign a unique port for payment service
    server.add_insecure_port(f'[::]:{port}')
    logging.info(f"PaymentService server started on port {port}")
    server.start()
    try:
        while True:
            time.sleep(86400)  # One day
    except KeyboardInterrupt:
        logging.info("PaymentService server shutting down.")
        server.stop(0)

if __name__ == '__main__':
    serve()
