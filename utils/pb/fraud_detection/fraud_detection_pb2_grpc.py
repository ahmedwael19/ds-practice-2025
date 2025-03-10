# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import fraud_detection_pb2 as fraud__detection__pb2


class FraudServiceStub(object):
    """
    FraudService is responsible for evaluating whether a transaction is fraudulent.

    The service consists of a single RPC method:
    - DetectFraud: Takes a FraudRequest containing user and credit card details and returns a FraudResponse 
    indicating whether the transaction is approved or flagged as fraudulent.
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.DetectFraud = channel.unary_unary(
                '/fraud.FraudService/DetectFraud',
                request_serializer=fraud__detection__pb2.FraudRequest.SerializeToString,
                response_deserializer=fraud__detection__pb2.FraudResponse.FromString,
                )


class FraudServiceServicer(object):
    """
    FraudService is responsible for evaluating whether a transaction is fraudulent.

    The service consists of a single RPC method:
    - DetectFraud: Takes a FraudRequest containing user and credit card details and returns a FraudResponse 
    indicating whether the transaction is approved or flagged as fraudulent.
    """

    def DetectFraud(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_FraudServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'DetectFraud': grpc.unary_unary_rpc_method_handler(
                    servicer.DetectFraud,
                    request_deserializer=fraud__detection__pb2.FraudRequest.FromString,
                    response_serializer=fraud__detection__pb2.FraudResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'fraud.FraudService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class FraudService(object):
    """
    FraudService is responsible for evaluating whether a transaction is fraudulent.

    The service consists of a single RPC method:
    - DetectFraud: Takes a FraudRequest containing user and credit card details and returns a FraudResponse 
    indicating whether the transaction is approved or flagged as fraudulent.
    """

    @staticmethod
    def DetectFraud(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/fraud.FraudService/DetectFraud',
            fraud__detection__pb2.FraudRequest.SerializeToString,
            fraud__detection__pb2.FraudResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
