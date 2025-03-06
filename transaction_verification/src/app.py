import sys
import os
import grpc
import logging
from concurrent import futures

FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2, transaction_verification_pb2_grpc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("transaction_verification")

class TransactionService(transaction_verification_pb2_grpc.TransactionServiceServicer):
    def VerifyTransaction(self, request, context):
        cid = "N/A"
        for key, value in context.invocation_metadata():
            if key == "correlation-id":
                cid = value
                break
        logger.info(f"[{cid}] Received VerifyTransaction request")
        response = transaction_verification_pb2.TransactionResponse()
        response.approved = True
        if request.items and len(request.credit_card.number) != 16:
            logger.info(f"[{cid}] Transaction invalid due to credit card number length")
            response.approved = False
        logger.info(f"[{cid}] VerifyTransaction completed with approved={response.approved}")
        return response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionServiceServicer_to_server(TransactionService(), server)
    port = "50052"
    server.add_insecure_port("[::]:" + port)
    logger.info(f"Transaction Verification Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()