import sys
import os
import grpc
import logging
from concurrent import futures

FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2, fraud_detection_pb2_grpc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("fraud_detection")

class FraudService(fraud_detection_pb2_grpc.FraudServiceServicer):
    def DetectFraud(self, request, context):
        cid = "N/A"
        for key, value in context.invocation_metadata():
            if key == "correlation-id":
                cid = value
                break
        logger.info(f"[{cid}] Received DetectFraud request for user: {request.user_info.name}")
        response = fraud_detection_pb2.FraudResponse()
        try:
            if not request.credit_card.number:
                msg = "Missing credit card number"
                logger.error(f"[{cid}] {msg}")
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(msg)
                response.approved = False
                return response
            response.approved = True
            logger.info(f"[{cid}] Fraud detection approved for user: {request.user_info.name}")
            return response
        except Exception as e:
            logger.exception(f"[{cid}] Exception in DetectFraud: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error")
            response.approved = False
            return response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    fraud_detection_pb2_grpc.add_FraudServiceServicer_to_server(FraudService(), server)
    port = "50051"
    server.add_insecure_port("[::]:" + port)
    logger.info(f"Fraud Detection Service started on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()