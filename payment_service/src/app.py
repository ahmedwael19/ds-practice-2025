import grpc
import time
import logging
from concurrent import futures
import sys
import os

# OpenTelemetry imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

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

# --- OpenTelemetry Setup ---
SERVICE_NAME = "payment-service"
resource = Resource.create({"service.name": SERVICE_NAME})

# Tracing
trace_exporter = OTLPSpanExporter(endpoint="http://observability:4318/v1/traces")
span_processor = BatchSpanProcessor(trace_exporter)
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(SERVICE_NAME)

# Metrics
metric_exporter = OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
metric_reader = PeriodicExportingMetricReader(metric_exporter)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(SERVICE_NAME)

# Define metrics
payments_prepared_counter = meter.create_counter(
    name="payments_prepared_total",
    description="Total number of payment preparations",
    unit="1"
)
payments_committed_counter = meter.create_counter(
    name="payments_committed_total",
    description="Total number of committed payments",
    unit="1"
)
payments_aborted_counter = meter.create_counter(
    name="payments_aborted_total",
    description="Total number of aborted payments",
    unit="1"
)
payment_commit_latency_histogram = meter.create_histogram(
    name="payment_commit_latency_seconds",
    description="Latency of payment commit operations",
    unit="s"
)

# In-memory store for transaction states
# Structure: {transaction_id: {"state": "PREPARED" | "COMMITTED" | "ABORTED", "details": ...}}
transactions = {}

class PaymentServiceServicer(payment_service_pb2_grpc.PaymentServiceServicer):
    def Prepare(self, request, context):
        with tracer.start_as_current_span("PreparePayment") as span:
            transaction_id = request.transaction_id
            order_id = request.order_id
            amount = request.amount
            span.set_attribute("transaction.id", transaction_id)
            span.set_attribute("order.id", order_id)
            span.set_attribute("amount", amount)
            logging.info(f"Prepare received for transaction_id: {transaction_id}, order_id: {order_id}, amount: {amount}")

            # Dummy validation/preparation logic
            if transaction_id in transactions and transactions[transaction_id]["state"] != "ABORTED":
                if transactions[transaction_id]["state"] == "PREPARED":
                    logging.warning(f"Transaction {transaction_id} already prepared. Voting COMMIT again.")
                    payments_prepared_counter.add(1, {"transaction_id": transaction_id})
                    return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_COMMIT, message="Already prepared")
                elif transactions[transaction_id]["state"] == "COMMITTED":
                    logging.error(f"Transaction {transaction_id} already committed. Cannot prepare again. Voting ABORT.")
                    payments_aborted_counter.add(1, {"transaction_id": transaction_id})
                    return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_ABORT, message="Transaction already committed")

            time.sleep(0.1) # Simulate I/O or processing
            transactions[transaction_id] = {
                "state": "PREPARED",
                "details": {"order_id": order_id, "amount": amount}
            }
            payments_prepared_counter.add(1, {"transaction_id": transaction_id})
            logging.info(f"Transaction {transaction_id} PREPARED. Voting COMMIT.")
            return payment_service_pb2.VoteResponse(transaction_id=transaction_id, vote=payment_service_pb2.VOTE_COMMIT, message="Payment prepared successfully")

    def Commit(self, request, context):
        with tracer.start_as_current_span("CommitPayment") as span:
            transaction_id = request.transaction_id
            span.set_attribute("transaction.id", transaction_id)
            logging.info(f"Commit received for transaction_id: {transaction_id}")
            start_time = time.time()
            if transaction_id not in transactions or transactions[transaction_id]["state"] != "PREPARED":
                logging.error(f"Cannot commit transaction {transaction_id}. State: {transactions.get(transaction_id, {}).get('state', 'NOT_FOUND')}")
                payments_aborted_counter.add(1, {"transaction_id": transaction_id})
                return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_FAILURE, message="Transaction not in PREPARED state or not found")

            logging.info(f"Executing dummy payment for transaction_id: {transaction_id}, details: {transactions[transaction_id]['details']}")
            time.sleep(0.2) # Simulate payment processing
            transactions[transaction_id]["state"] = "COMMITTED"
            payments_committed_counter.add(1, {"transaction_id": transaction_id})
            payment_commit_latency_histogram.record(time.time() - start_time, {"transaction_id": transaction_id})
            logging.info(f"Transaction {transaction_id} COMMITTED.")
            return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Payment committed successfully")

    def Abort(self, request, context):
        with tracer.start_as_current_span("AbortPayment") as span:
            transaction_id = request.transaction_id
            span.set_attribute("transaction.id", transaction_id)
            logging.info(f"Abort received for transaction_id: {transaction_id}")
            if transaction_id not in transactions:
                logging.warning(f"Transaction {transaction_id} not found for Abort. Assuming already handled or never prepared.")
                payments_aborted_counter.add(1, {"transaction_id": transaction_id})
                return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Transaction not found, abort acknowledged")
            current_state = transactions[transaction_id]["state"]
            if current_state == "COMMITTED":
                logging.error(f"CRITICAL: Received Abort for already COMMITTED transaction {transaction_id}. This indicates a serious issue in the 2PC protocol or coordinator logic.")
                payments_aborted_counter.add(1, {"transaction_id": transaction_id})
                return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_FAILURE, message="Transaction already committed, cannot abort")
            if current_state == "ABORTED":
                logging.info(f"Transaction {transaction_id} already ABORTED. Acknowledging abort again.")
                return payment_service_pb2.AckResponse(transaction_id=transaction_id, status=payment_service_pb2.ACK_SUCCESS, message="Transaction already aborted")

            logging.info(f"Aborting transaction_id: {transaction_id}. Releasing resources (dummy).")
            time.sleep(0.1)
            transactions[transaction_id]["state"] = "ABORTED"
            payments_aborted_counter.add(1, {"transaction_id": transaction_id})
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
