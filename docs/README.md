# E-Commerce Checkout System

## Overview
This project implements a **microservices-based architecture** using **gRPC** and **Flask** to facilitate transaction validation and book recommendation services. The system consists of multiple services communicating over gRPC, with an **Orchestrator API** acting as a central gateway.

## Services Overview

1. **Frontend**
   - Provides checkout interface for customers
   - Submits orders to the orchestrator
   - Displays order status and book recommendations

2. **Orchestrator**
   - Coordinates the checkout workflow using Flask
   - Manages vector clocks for causal consistency
   - Routes events to appropriate services following DAG dependencies
   - Enqueues approved orders for processing
   - Returns responses to clients before order fulfillment completes

3. **Transaction Verification**
   - Validates transaction data integrity
   - Verifies items and quantities
   - Checks user data completeness
   - Validates credit card format and expiration

4. **Fraud Detection**
   - Evaluates transactions for potential fraud using AI
   - Performs OpenAI-powered analysis of user data patterns
   - Implements confidence-based approval system for AI judgments
   - Checks credit card velocity (frequency of use) to detect suspicious activity
   - Falls back to rule-based checks when AI is unavailable

5. **Suggestions**
   - Provides personalized book recommendations using AI
   - Leverages OpenAI to generate contextually relevant book suggestions
   - Analyzes purchased items to generate relevant recommendations
   - Implements fallback mechanisms for AI service failures

6. **Order Queue**
   - Buffers approved orders for processing
   - Maintains priority-based order queue with heapq
   - Provides queue status information
   - Prioritizes orders based on quantity, shipping method, and gift wrapping status

7. **Order Executor Cluster**
   - Three executor instances implementing the Raft Algorithm
   - Processes orders from the queue when elected as leader
   - Maintains high availability through redundancy


## System Model

### Communication Model
- **Hybrid Communication Pattern**: Synchronous gRPC for service validation steps; asynchronous order processing
- **Vector Clock Propagation**: All services use vector clocks to track causality between distributed events  
- **Request Correlation**: Each request is tracked with a unique correlation ID across service boundaries
- **Service Discovery**: Services locate each other via container names in the Docker network

### Architectural Model
- **Microservices Architecture**: System composed of independent, specialized services
- **API Gateway Pattern**: Orchestrator coordinates workflow and manages client interaction
- **Event-Driven Processing**: System follows a directed acyclic graph (DAG) of events with dependencies
- **Service-Local State**: Each service maintains its own cache of order data
- **Docker Containerization**: All components run as containers managed by Docker Compose

### Timing Model
- **Vector Clocks**: Each service maintains a vector clock to track event causality
- **Event Dependencies**: Events follow a partial ordering determined by the directed acyclic graph
- **Clock Synchronization**: Services merge vector clocks during communication
- **Election Timeouts**: Order executors use randomized timeouts (1.5-3 seconds) for election initiation

### Failure Model
- **Service Not Found Handling**: System checks for missing data/services and handles errors gracefully
- **Vector Clock Conflict Detection**: System detects vector clock causality violations
- **Leader Election**: Order executor cluster implements the Raft Algorithm for leader election
- **Heartbeat Monitoring**: Leaders send periodic heartbeats (every 500ms) to maintain leadership
- **Graceful AI Degradation**: System continues processing even if AI services fail or return unexpected results


## Project Structure

```
project/
├── orchestrator/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # API gateway and workflow coordinator
├── transaction_verification/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # Transaction validation service
├── fraud_detection/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # AI-powered fraud detection service
├── suggestions/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # AI-powered book recommendations service
├── order_queue/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # Order queue service
├── order_executor/
│   ├── Dockerfile
│   └── src/
│       └── app.py             # Order executor with Raft Algorithm
├── frontend/
│   ├── Dockerfile
│   └── src/
│       └── index.html         # Checkout form UI
├── utils/
│   └── pb/                    # Protocol buffer definitions
│       ├── fraud_detection/
│       │   ├── fraud_detection.proto
│       │   └── ...
│       ├── transaction_verification/
│       │   ├── transaction_verification.proto
│       │   └── ...
│       ├── suggestions/
│       │   ├── suggestions.proto
│       │   └── ...
│       ├── order_queue/
│       │   ├── order_queue.proto
│       │   └── ...
│       └── order_executor/
│           ├── order_executor.proto
│           └── ...
├── docker-compose.yaml        # Service orchestration
└── variables.env              # Environment variables including OpenAI API key
```

## Service Communication Flow

1. **Initialization Phase**:
   - Orchestrator receives HTTP checkout request
   - Generates unique order ID and correlation ID
   - Initializes all services in parallel with order data
   - Each service caches data and responds with updated vector clock
   - Orchestrator merges vector clocks

2. **Event Execution Phase**:
   - **Events a & b** (parallel): Verify items and user data
   - **Events c & d** (parallel, with dependencies):
     - c (VerifyCreditCardFormat) depends on a completion
     - d (CheckUserData) depends on b completion
   - **Event e** (after c & d): Check credit card for fraud
   - **Event f** (after e): Get AI-generated book suggestions
   - Each event updates and propagates vector clocks

3. **Order Processing Phase**:
   - Orchestrator enqueues approved order in priority queue
   - Returns response to client immediately after enqueuing
   - Leader in executor cluster asynchronously dequeues and processes orders

4. **Cleanup Phase**:
   - Orchestrator sends final vector clock to all services
   - Services clear cached order data if vector clock indicates all events are complete

## Priority Queue Implementation

- **Input Factors**:
  - Item quantity (larger orders get higher priority)
  - Shipping method (express > priority > standard)
  - Gift wrapping status (wrapped items get higher priority)
  
- **Implementation Details**:
  - Uses Python's `heapq` for efficient priority management
  - Thread-safe with locking mechanisms
  - Includes randomness factor to prevent starvation
  - Lower priority value = higher processing priority

## AI Integration

### Fraud Detection AI
- **Model**: Uses OpenAI's GPT-4o-mini model
- **Prompt Engineering**: Structured prompts with clear JSON response formats
- **Confidence Scoring**: AI provides confidence level with each fraud assessment
- **Low-Confidence Handling**: Orders with low-confidence fraud indicators are approved but logged
- **Fallback Mechanism**: System continues with rule-based checks when AI service fails

### Recommendations AI 
- **Model**: Uses OpenAI's GPT-4o-mini model
- **Personalization**: Generates book recommendations based on purchased items
- **JSON Structure**: Returns structured data with book titles, authors, and IDs
- **Error Handling**: Implements fallback recommendations when AI response parsing fails

## API Endpoints

### POST /checkout

| Endpoint       | Method | Description |
|----------------|--------|-------------|
| `/checkout`    | `POST` | Validates transactions and returns order status with book suggestions if approved |
## Example Checkout Request

```json
{
  "items": [
    {
      "name": "Clean Architecture",
      "quantity": 1
    }
  ],
  "user": {
    "name": "John Doe",
    "contact": "john@example.com"
  },
  "creditCard": {
    "number": "4111111111111111",
    "expirationDate": "12/2025",
    "cvv": "123"
  },
  "billingAddress": {
    "street": "123 Main St",
    "city": "Anytown",
    "state": "CA",
    "zip": "12345",
    "country": "USA"
  },
  "shippingMethod": "standard",
  "giftWrapping": false,
  "termsAndConditionsAccepted": true
}
```

## Example Response

```json
{
  "orderId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "Order Approved",
  "message": "Your order has been approved. Order has been queued for processing.",
  "suggestedBooks": [
    {
      "title": "Domain-Driven Design",
      "author": "Eric Evans",
      "category": "Software Engineering"
    },
    {
      "title": "Patterns of Enterprise Application Architecture",
      "author": "Martin Fowler",
      "category": "Software Engineering"
    },
    {
      "title": "Clean Code",
      "author": "Robert C. Martin",
      "category": "Software Engineering"
    }
  ],
  "finalVectorClock": {
    "orchestrator": 1,
    "transaction_verification": 4,
    "fraud_detection": 3,
    "suggestions": 2
  }
}
```

## System Diagram

```mermaid
sequenceDiagram
    participant Client
    participant Orchestrator
    participant TV as Transaction Verification
    participant FD as Fraud Detection
    participant S as Suggestions
    participant OQ as Order Queue
    participant OE as Order Executor

    Client->>Orchestrator: POST /checkout
    
    par Initialize Services
        Orchestrator->>TV: InitializeTransaction
        Orchestrator->>FD: InitializeFraudDetection
        Orchestrator->>S: InitializeSuggestions
    end
    
    TV-->>Orchestrator: InitResponse(VC)
    FD-->>Orchestrator: InitResponse(VC)
    S-->>Orchestrator: InitResponse(VC)
    
    par Events a & b (Parallel)
        Orchestrator->>TV: VerifyItems (a)
        Orchestrator->>TV: VerifyUserData (b)
    end
    
    TV-->>Orchestrator: VerifyItems Response(VC)
    TV-->>Orchestrator: VerifyUserData Response(VC)
    
    Note over Orchestrator: Merge clocks from a & b
    
    par Events c & d (Parallel, but with dependencies)
        Orchestrator->>TV: VerifyCreditCardFormat (c) [depends on a]
        Orchestrator->>FD: CheckUserData (d) [depends on b]
    end
    
    Note over FD: AI-powered fraud analysis
    TV-->>Orchestrator: VerifyCreditCardFormat Response(VC)
    FD-->>Orchestrator: CheckUserData Response(VC)
    
    Note over Orchestrator: Merge clocks from c & d
    
    Orchestrator->>FD: CheckCreditCardData (e) [depends on c & d]
    FD-->>Orchestrator: CheckCreditCardData Response(VC)
    
    Orchestrator->>S: GetSuggestions (f) [depends on e]
    Note over S: AI-powered book recommendations
    S-->>Orchestrator: GetSuggestions Response(VC)
    
    Note over Orchestrator: Order Approved
    
    Orchestrator->>OQ: EnqueueOrder
    OQ-->>Orchestrator: EnqueueResponse
    
    Orchestrator-->>Client: HTTP Response
    
    Note over Client,Orchestrator: Client receives response before processing completes
    
    OE->>OQ: DequeueOrder (asynchronous)
    OQ-->>OE: DequeueResponse
    Note over OE: Order processed asynchronously
    
    par Clear Caches
        Orchestrator->>TV: ClearTransactionCache
        Orchestrator->>FD: ClearFraudCache
        Orchestrator->>S: ClearSuggestionsCache
    end
```

## Architecture Diagram

```mermaid
graph TD;
    User["👤 User"] -->|HTTP Request| Orchestrator[🟢 Orchestrator API :5000];
    
    Orchestrator -->|gRPC :50052| TransactionVerification[💳 Transaction Verification Service];
    Orchestrator -->|gRPC :50051| FraudDetection[🔍 AI Fraud Detection Service];
    Orchestrator -->|gRPC :50053| Suggestions[📚 AI Book Suggestions Service];
    
    FraudDetection -->|API Call| OpenAI[☁️ OpenAI GPT API];
    Suggestions -->|API Call| OpenAI;
    
    Orchestrator -->|gRPC :50054| OrderQueue[📋 Priority Order Queue Service];
    
    OrderExecutor1["⚙️ Order Executor 1 (Raft Node)"] -.->|Poll for Orders| OrderQueue;
    OrderExecutor2["⚙️ Order Executor 2 (Raft Node)"] -.->|Poll for Orders| OrderQueue;
    OrderExecutor3["⚙️ Order Executor 3 (Raft Node)"] -.->|Poll for Orders| OrderQueue;
    
    OrderExecutor1 -.->|Raft Consensus| OrderExecutor2;
    OrderExecutor2 -.->|Raft Consensus| OrderExecutor3;
    OrderExecutor3 -.->|Raft Consensus| OrderExecutor1;
    
    TransactionVerification -->|gRPC Response| Orchestrator;
    FraudDetection -->|gRPC Response| Orchestrator;
    Suggestions -->|gRPC Response| Orchestrator;

    Orchestrator -->|HTTP Response| User;
    
    Note["🔑 Only elected Raft leader processes orders"]
    OrderExecutor1 --- Note;
    OrderExecutor2 --- Note;
    OrderExecutor3 --- Note;
```

## Vector Diagram

![alt text](vector_diagram.png "Vector Diagram")

## Cache Clearing with Vector Clock Safety

- **Orchestrator** sends final vector clock to each service after order processing is complete
- **Services** verify that their local vector clock ≤ final vector clock before clearing cached order data
- **Conflict Detection** occurs if local clock shows events not captured in final clock
- **Safety Checks** prevent inconsistent data cleanup


## Leader Election Diagram

The order executor instances implement the Raft consensus algorithm for leader election:

### Sequence 1: Initial Election

```mermaid
sequenceDiagram
    participant E1 as Executor 1
    participant E2 as Executor 2
    participant E3 as Executor 3
    
    Note over E1,E3: All nodes start as Followers with random election timeouts
    
    Note over E2: Timeout expires first (1.8s)
    
    E2->>E2: Becomes Candidate
    E2->>E2: Increments term to 1
    E2->>E2: Votes for self
    
    E2->>E1: RequestVote(term=1)
    E2->>E3: RequestVote(term=1)
    
    E1-->>E2: VoteGranted=true
    E3-->>E2: VoteGranted=true
    
    Note over E2: Received majority (3/3)
    Note over E2: Becomes Leader for term 1
    
    E2->>E1: Heartbeat(term=1)
    E2->>E3: Heartbeat(term=1)
    
    Note over E1: Reset timeout
    Note over E3: Reset timeout
```

### Sequence 2: Leader Failure and Re-election

```mermaid
sequenceDiagram
    participant E1 as Executor 1
    participant E2 as Executor 2
    participant E3 as Executor 3
    
    Note over E2: Leader for term 1
    
    E2->>E1: Heartbeat(term=1)
    E2->>E3: Heartbeat(term=1)
    
    Note over E1: Reset timeout
    Note over E3: Reset timeout
    
    Note over E2: Leader crashes!
    
    Note over E1,E3: No heartbeats received
    
    Note over E3: Timeout expires first (2.1s)
    
    E3->>E3: Becomes Candidate
    E3->>E3: Increments term to 2
    E3->>E3: Votes for self
    
    E3->>E1: RequestVote(term=2)
    E3-xE2: RequestVote(term=2)
    
    E1-->>E3: VoteGranted=true
    
    Note over E3: Received majority (2/3)
    Note over E3: Becomes Leader for term 2
    
    E3->>E1: Heartbeat(term=2)
    
    Note over E1: Reset timeout
```

### Sequence 3: Network Partition and Recovery

```mermaid
sequenceDiagram
    participant E1 as Executor 1
    participant E2 as Executor 2 (Restarted)
    participant E3 as Executor 3
    
    Note over E3: Leader for term 2
    
    E3->>E1: Heartbeat(term=2)
    E3->>E2: Heartbeat(term=2)
    
    Note over E1,E2: Reset timeout
    
    Note over E1,E3: Network partition!
    
    Note over E1: Timeout expires
    E1->>E1: Becomes Candidate
    E1->>E1: Increments term to 3
    E1->>E1: Votes for self
    
    E1-xE3: RequestVote(term=3)
    E1->>E2: RequestVote(term=3)
    
    E2-->>E1: VoteGranted=true
    
    Note over E1: Received majority in partition (2/3)
    Note over E1: Becomes Leader for term 3
    
    E1->>E2: Heartbeat(term=3)
    
    Note over E1,E3: Partition heals
    
    E1->>E3: Heartbeat(term=3)
    
    Note over E3: Discovers higher term
    Note over E3: Steps down, becomes Follower
    
    E3-->>E1: Accept Heartbeat(term=3)
    
    Note over E1: Remains Leader for term 3
    Note over E1: Now serving all nodes
```

The Raft leader election algorithm ensures:
1. Only one leader exists in a given term
2. Leaders maintain authority through regular heartbeats
3. Nodes step down when discovering higher terms
4. The system recovers automatically after failures
5. Only the leader processes orders from the queue
6. Split votes are resolved through randomized timeouts
7. Network partitions are handled when healed

## Consistency Protocol diagram: 
The following diagrams illustrate the consistency protocol for the database module which relies heavily on RAFT
```mermaid
graph TD
    subgraph "Order Execution Layer"
        OE_Leader["Order Executor (Leader Instance)"]
    end

    subgraph "Books Database Cluster (Replicated Key-Value Store)"
        direction LR
        DBP["DB Node 1 (Primary - Raft Leader)"]
        DBB1["DB Node 2 (Backup - Raft Follower)"]
        DBB2["DB Node 3 (Backup - Raft Follower)"]

        style DBP fill:#87CEEB,stroke:#333,stroke-width:2px,color:#000
        style DBB1 fill:#D3D3D3,stroke:#333,stroke-width:2px,color:#000
        style DBB2 fill:#D3D3D3,stroke:#333,stroke-width:2px,color:#000

        DBP_Store["Local K-V Store (Book Stock)"]
        DBB1_Store["Local K-V Store (Book Stock)"]
        DBB2_Store["Local K-V Store (Book Stock)"]

        DBP --- DBP_Store
        DBB1 --- DBB1_Store
        DBB2 --- DBB2_Store

        %% Raft Communication for DB Leader Election & Heartbeats
        DBP <-. "Raft Protocol" .-> DBB1
        DBP <-. "Raft Protocol" .-> DBB2
        DBB1 <-. "Raft Protocol" .-> DBB2
    end

    %% Client (Order Executor) Operations
    OE_Leader -- "Write Ops (e.g., DecrementStock) <br/> Read Ops (e.g., ReadStock)" --> DBP

    %% Primary to Backup Replication
    DBP -.->|Internal Data Replication| DBB1
    DBP -.->|Internal Data Replication| DBB2

    %% Backup to Primary Acknowledgements
    DBB1 -.->|Replication ACK| DBP
    DBB2 -.->|Replication ACK| DBP


    classDef client fill:#f9f,stroke:#333,stroke-width:2px;
    class OE_Leader client;
```

```mermaid
sequenceDiagram
    participant OE as "Order Executor (Leader)"
    participant DBP as "Books DB Primary (Raft Leader)"
    participant DBB1 as "Books DB Backup 1 (Raft Follower)"
    participant DBB2 as "Books DB Backup 2 (Raft Follower)"

    Note over DBP and DBB1 and DBB2: Books Database Nodes form a Raft Group for Primary Election

    OE->>DBP: 1. DecrementStockRequest(book_id, amount)
    activate DBP
    Note right of DBP: Acquires lock for book_id
    DBP->>DBP: 2. Applies change locally (datastore[book_id] -= amount)

    par Replicate to Backups
        DBP->>DBB1: 3a. InternalReplicateRequest(book_id, new_quantity)
        activate DBB1
        DBB1->>DBB1: Applies change locally
        DBB1-->>DBP: 4a. Ack (InternalReplicateResponse)
        deactivate DBB1
    and
        DBP->>DBB2: 3b. InternalReplicateRequest(book_id, new_quantity)
        activate DBB2
        DBB2->>DBB2: Applies change locally
        DBB2-->>DBP: 4b. Ack (InternalReplicateResponse)
        deactivate DBB2
    end

    Note right of DBP: Waits for quorum of Acks (including self)
    Note right of DBP: Releases lock for book_id
    DBP-->>OE: 5. DecrementStockResponse(success=true, new_quantity)
    deactivate DBP

    %% Read Operation (Directed to Primary)
    OE->>DBP: 6. ReadStockRequest(book_id)
    activate DBP
    Note right of DBP: (May acquire read lock or use consistent snapshot)
    DBP->>DBP: 7. Reads from local datastore
    DBP-->>OE: 8. ReadStockResponse(quantity)
    deactivate DBP

    %% Raft Heartbeats for DB Cluster (background)
    loop DB Raft Heartbeats
        DBP->>DBB1: DBAppendEntriesRequest (Heartbeat)
        DBB1-->>DBP: DBAppendEntriesResponse
        DBP->>DBB2: DBAppendEntriesRequest (Heartbeat)
        DBB2-->>DBP: DBAppendEntriesResponse
    end

    %% Raft Leader Election (if DBP fails)
    Note over DBP and DBB1 and DBB2: If DBP fails, backups will hold an election
```


## Commitment Protocol (2PC)
The following diagrams illustrate the successful and unsuccesful flow in relation to the commitment protocol.

__Scenario 1: Successful Commit__

```mermaid
sequenceDiagram
    participant OE as Order Executor (Coordinator)
    participant PS as Payment Service (Participant)
    participant DB as Books Database (Participant)

    Note over OE: Order processing begins...
    OE->>+PS: Prepare(tx_id, order_details)
    OE->>+DB: PrepareTransaction(tx_id, db_ops)

    Note over PS: Validate payment, stage resources
    PS-->>-OE: VOTE_COMMIT(tx_id)

    Note over DB: Check stock, stage changes
    DB-->>-OE: DB_VOTE_COMMIT(tx_id)

    Note over OE: Both voted COMMIT. Decision: Global Commit.
    OE->>+PS: Commit(tx_id)
    OE->>+DB: CommitTransaction(tx_id)

    Note over PS: Execute payment, release resources
    PS-->>-OE: ACK_SUCCESS(tx_id)

    Note over DB: Apply stock changes, replicate
    DB-->>-OE: DB_ACK_SUCCESS(tx_id)

    Note over OE: Transaction successful. Finalize order.
```
__Scenario 2: Abort (e.g., Database votes Abort)__

```mermaid
sequenceDiagram
    participant OE as Order Executor (Coordinator)
    participant PS as Payment Service (Participant)
    participant DB as Books Database (Participant)

    Note over OE: Order processing begins...
    OE->>+PS: Prepare(tx_id, order_details)
    OE->>+DB: PrepareTransaction(tx_id, db_ops)

    Note over PS: Validate payment, stage resources
    PS-->>-OE: VOTE_COMMIT(tx_id)

    Note over DB: Check stock - Fails (e.g., insufficient)
    DB-->>-OE: DB_VOTE_ABORT(tx_id, "Insufficient stock")

    Note over OE: DB voted ABORT. Decision: Global Abort.
    OE->>+PS: Abort(tx_id)  // Abort Payment Service as it was prepared
    OE->>+DB: AbortTransaction(tx_id) // Also inform DB, though it already voted abort

    Note over PS: Release staged resources
    PS-->>-OE: ACK_SUCCESS(tx_id)

    Note over DB: Discard staged changes (if any were staged before abort decision)
    DB-->>-OE: DB_ACK_SUCCESS(tx_id)

    Note over OE: Transaction aborted. Handle failure.
```
---

## Project Contributors

| Name              | Email             |
|-------------------|-------------------|
| **Ahmed Soliman** | soliman@ut.ee     |
| **Buraq Khan**    | buraq@ut.ee       |