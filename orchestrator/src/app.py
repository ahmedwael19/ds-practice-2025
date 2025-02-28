import sys
import os

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")

fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2,fraud_detection_pb2_grpc

transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2, transaction_verification_pb2_grpc

suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2, suggestions_pb2_grpc
import grpc
from concurrent.futures import ThreadPoolExecutor, as_completed # for multi-threading

def call_fraud_detection(order_data):
    user_name = order_data.get("user",{}).get("name","unknown") # get the user data from the order data
    with grpc.insecure_channel("fraud_detection:50051") as channel: # same as the dummy greet function
        stub = fraud_detection_pb2_grpc.FraudServiceStub(channel)
        response = stub.DetectFraud(fraud_detection_pb2.FraudRequest(name=user_name)) # dummy fraud detection for now #TODO: ADD LOGIC
    return {"fraud_detection": response.message}

# Helper to call the transaction verification service via HTTP #TODO: ADD LOGIC
def call_transaction_verification(order_data):

    user_name = order_data.get("user",{}).get("name","unknown") # get the user data from the order data
    with grpc.insecure_channel("transaction_verification:50052") as channel: # same as the dummy greet function
        stub = transaction_verification_pb2_grpc.TransactionServiceStub(channel)
        response = stub.VerifyTransaction(transaction_verification_pb2.TransactionRequest(name=user_name)) #TODO: ADD LOGIC
    return {"transaction_verification": response.message}

# Helper to call the suggestions service via HTTP # TODO: ADD LOGIC

def call_suggestions(order_data):
    user_name = order_data.get("user",{}).get("name","unknown") # get the user data from the order data
    with grpc.insecure_channel("suggestions:50053") as channel: # same as the dummy greet function
        stub = suggestions_pb2_grpc.SuggestionsServiceStub(channel)
        response = stub.GetSuggestions(suggestions_pb2.SuggestionRequest(name=user_name)) #TODO: ADD LOGIC
    return {"suggestions": response.message}

# Import Flask.
# Flask is a web framework for Python.
# It allows you to build a web application quickly.
# For more information, see https://flask.palletsprojects.com/en/latest/
from flask import Flask, request, jsonify
from flask_cors import CORS
import json

# Create a simple Flask app.
app = Flask(__name__)
# Enable CORS for the app.
CORS(app, resources={r'/*': {'origins': '*'}})

@app.route('/checkout', methods=['POST'])
def checkout():
    # Get request object data to json
    order_data = json.loads(request.data)
    results = {}
    # Use a ThreadPoolExecutor to run service calls in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(call_fraud_detection, order_data),
            executor.submit(call_transaction_verification, order_data),
            executor.submit(call_suggestions, order_data)
        ]
        # gather the data when done
        for future in as_completed(futures):
            results.update(future.result())
    order_status= "Order Approved" # by default
    for service , result in results.items():
        if isinstance(result, dict) and result.get("error"): # if any of them have errors, then the order is rejected.
            order_status = "Order Rejected"
            break
    final_response = {
        "orderId": "12345",  # Replace with proper order ID generation
        "status": order_status,
        "results": results,
    }

    return jsonify(final_response)


if __name__ == '__main__':
    # Run the app in debug mode to enable hot reloading.
    # This is useful for development.
    # The default port is 5000.
    app.run(host='0.0.0.0')
