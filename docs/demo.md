
## Bonus Features Implementation

### 1. Priority Queue Implementation 


```python
def _calculate_priority(self, order_data):
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
        
    # Add some randomness to avoid starvation
    priority -= int(time.time() % 100) / 100
    
    return priority
```

uses Python's `heapq` for efficiency and includes a lock for thread safety.

### 2. N-Replica Resilience with Raft Consensus

`RaftConsensus` class implements the full Raft algorithm with:
- Randomized election timeouts (1.5-3s)
- Term-based leader election
- Majority-based voting (`self.votes_received > (len(self.peers) + 1) / 2`)
- Heartbeat mechanism every 500ms
- Proper state transitions (follower → candidate → leader)

This works for any number of replicas as long as a majority is available.

### 3. Cache Clearing with Vector Clocks 

cache clearing in the orchestrator with final vector clock propagation:

```python
# In orchestrator.py
if final_clock_dict:
    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(call_clear_cache, "transaction", "transaction_verification:50052", order_id, final_clock_dict, cid)
        executor.submit(call_clear_cache, "fraud", "fraud_detection:50051", order_id, final_clock_dict, cid)
        executor.submit(call_clear_cache, "suggestions", "suggestions:50053", order_id, final_clock_dict, cid)
```

Each service implements vector clock safety checks before clearing:

```python
# Check if our vector clock is <= the final vector clock
is_safe_to_clear = True
for service, time in local_clock.items():
    if time > final_clock.get(service, 0):
        is_safe_to_clear = False
        # Log warning about vector clock conflict
```
## Postman Demo Plan

Create a Postman collection with the following requests to showcase  bonus features:

### 1. Priority Queue Demo

**Scenario: Different Order Priorities**

1. **Create High-Priority Order**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "War and Peace", "quantity": 12}],
     "user": {"name": "VIP Customer", "contact": "vip@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "express",
     "giftWrapping": true,
     "termsAndConditionsAccepted": true
   }
   ```

2. **Create Medium-Priority Order**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "The Great Gatsby", "quantity": 6}],
     "user": {"name": "Regular Customer", "contact": "regular@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "456 Oak St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "priority",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

3. **Create Low-Priority Order**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "Short Stories", "quantity": 1}],
     "user": {"name": "Basic Customer", "contact": "basic@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "789 Elm St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "standard",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

**What to show:**
- Send these requests in reverse order (Low → Medium → High)
- Monitor the order executor logs
- Note how they're processed in priority order (High → Medium → Low)
- Point to the `_calculate_priority` function in  code

### 2. Raft Consensus Demo

**Scenario: Leader Election and Failure Recovery**

1. **Initial Leader Status Check**
   ```
   # Create a simple GET endpoint for this or use docker logs
   docker logs ds-practice-2025-1_order_executor_1_1 | grep "became leader"
   docker logs ds-practice-2025-1_order_executor_2_1 | grep "became leader"
   docker logs ds-practice-2025-1_order_executor_3_1 | grep "became leader"
   ```

2. **Process a Normal Order**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "Clean Code", "quantity": 1}],
     "user": {"name": "Test Customer", "contact": "test@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "standard",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

3. **Simulate Leader Failure**
   ```
   # Stop the current leader (if executor_2 is leader)
   docker stop ds-practice-2025-1_order_executor_2_1
   ```

4. **Process Another Order After Leader Failure**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "Domain-Driven Design", "quantity": 1}],
     "user": {"name": "Another Customer", "contact": "another@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "standard",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

5. **Restore Failed Node**
   ```
   docker start ds-practice-2025-1_order_executor_2_1
   ```

**What to show:**
- The initial leader election logs
- How the system continues to function after leader failure
- The new leader election process
- How the restored node rejoins the cluster

### 3. Vector Clock Cache Clearing Demo

**Scenario: Cache Clearing With Vector Clock Safety**

1. **Normal Order Processing**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "Clean Architecture", "quantity": 1}],
     "user": {"name": "Sample Customer", "contact": "sample@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "standard",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

2. **Examine Cache Clearing Logs**
   ```
   docker logs ds-practice-2025-1_orchestrator_1 | grep "Cache Clearing Step"
   docker logs ds-practice-2025-1_transaction_verification_1 | grep "cleared from cache"
   docker logs ds-practice-2025-1_fraud_detection_1 | grep "cleared from cache"
   docker logs ds-practice-2025-1_suggestions_1 | grep "cleared from cache"
   ```

**What to show:**
- The final vector clock in the response
- Logs showing safe cache clearing operations
- The vector clock safety check code in  services

### 4. AI Integration Demo

**Scenario: AI-Powered Fraud Detection and Recommendations**

1. **Process Order with AI Services**
   ```
   POST http://localhost:8081/checkout
   {
     "items": [{"name": "The Pragmatic Programmer", "quantity": 1}],
     "user": {"name": "AI Test Customer", "contact": "ai.test@example.com"},
     "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
     "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
     "shippingMethod": "standard",
     "giftWrapping": false,
     "termsAndConditionsAccepted": true
   }
   ```

**What to show:**
- The AI-generated book recommendations in the response
- Logs from fraud detection showing AI analysis
- Logs from suggestions showing AI generation
- The AI integration code in both services

## Demonstration Script

1. Start by explaining the bonus features you've implemented
2. Show the relevant code sections briefly
3. Run through each Postman request sequence
4. Highlight the logs that demonstrate the features working
5. Explain how these features enhance the system's resilience and functionality

By following this demo plan, you'll effectively showcase all the bonus features you've implemented, demonstrating  system's sophisticated design and earning the extra points.


# Analysis of Order Priority System & Testing Strategy

## Is there a bug in the response mechanism?

**No, this is not a bug.** The system is designed to work asynchronously by design:

1. The orchestrator service processes the checkout request through steps a-f, verifying the order validity
2. If approved, it enqueues the order in the order queue service
3. It then returns a response to the client indicating the order has been accepted and queued

The actual processing of the order by an executor happens asynchronously after the response is sent. This is a common pattern in distributed systems that separates:
- **Order validation/acceptance** (synchronous - client waits for this)
- **Order processing/fulfillment** (asynchronous - happens in the background)

The message in the response correctly states "Order has been queued for processing" which accurately reflects the system's state. The client doesn't need to wait for the entire fulfillment process to complete before getting a response.

## Simulating Multiple Orders with Different Priorities

Looking at the `_calculate_priority` method in app.py, priorities are determined by:

```python
def _calculate_priority(self, order_data):
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
```

To test different priorities, create orders with:

### High Priority Order
```json
{
  "items": [
    {"name": "War and Peace", "quantity": 12}
  ],
  "shippingMethod": "express",
  "giftWrapping": true,
  "user": {"name": "VIP Customer", "contact": "vip@example.com"},
  "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
  "billingAddress": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
  "termsAndConditionsAccepted": true
}
// Priority: -65 (very high)
```

### Medium Priority Order
```json
{
  "items": [
    {"name": "The Great Gatsby", "quantity": 6}
  ],
  "shippingMethod": "priority",
  "giftWrapping": false,
  "user": {"name": "Regular Customer", "contact": "regular@example.com"},
  "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
  "billingAddress": {"street": "456 Oak St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
  "termsAndConditionsAccepted": true
}
// Priority: -35 (medium)
```

### Low Priority Order
```json
{
  "items": [
    {"name": "Short Stories", "quantity": 1}
  ],
  "shippingMethod": "standard",
  "giftWrapping": false,
  "user": {"name": "Basic Customer", "contact": "basic@example.com"},
  "creditCard": {"number": "4111111111111111", "expirationDate": "12/2025", "cvv": "123"},
  "billingAddress": {"street": "789 Elm St", "city": "Anytown", "state": "CA", "zip": "12345", "country": "USA"},
  "termsAndConditionsAccepted": true
}
// Priority: 0 (lowest)
```

## Using Postman to Simulate Multiple Requests

### Method 1: Postman Collection Runner

1. **Create a Collection with  requests**:
   - Create a new collection in Postman
   - Add  different order requests to the collection

2. **Run the Collection**:
   - Click "Runner" button in the Postman header
   - Select  collection
   - Set the number of iterations 
   - Configure the delay between requests (e.g., 500ms)
   - Click "Run" button

### Method 2: Using Postman Scripts

```javascript
// Add this in the "Tests" tab of  request
const iterations = 5; // Number of requests to send
const delay = 1000; // Delay between requests in ms

// Only if not the last iteration
if (pm.iterationData.iteration < iterations - 1) {
    setTimeout(() => {
        pm.sendRequest(pm.request, function (err, response) {
            console.log(`Request ${pm.iterationData.iteration + 2} sent`);
        });
    }, delay);
}
```

### Method 3: Bulk Import & Run

1. Create a CSV or JSON file with different request data
2. Import into Postman using Collection Runner's "Data" option
3. Run the collection with the imported data

### Monitoring Results

To verify the priority queue works:
1. Send requests in reverse priority order (low → medium → high)
2. Monitor the order executor logs with:
   ```bash
   docker logs -f ds-practice-2025-1_order_executor_1_1 | grep "Processing order"
   ```
3. You should see orders processed in priority order (high → medium → low)

You can also monitor the order queue to see how items are enqueued:
```bash
docker logs -f ds-practice-2025-1_order_queue_1 | grep "Enqueued order"
```

This will confirm that  priority system is working as expected.