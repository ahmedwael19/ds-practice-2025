import requests
import time
import pytest
import uuid
import random # For more varied CC numbers if needed
from concurrent.futures import ThreadPoolExecutor, as_completed

ORCHESTRATOR_URL = "http://localhost:8081" # As mapped in docker-compose for orchestrator

# These MUST map correctly to the book_ids used in your BooksDatabase and OrderExecutor logic
BOOK_MAPPINGS = {
    "Clean Code": "book_101_clean_code",
    "Pragmatic Programmer": "book_102_pragmatic_programmer",
    "Design Patterns": "book_103_design_patterns",
    "Domain-Driven Design": "book_104_domain_driven_design",
}

# --- Helper to get stock (via Orchestrator's test endpoint) ---
def get_book_stock(book_id: str):
    """Queries the orchestrator's /stock/read endpoint to get current stock for a book_id."""
    try:
        res = requests.get(f"{ORCHESTRATOR_URL}/stock/read", params={"book_id": book_id}, timeout=10) # Increased timeout
        if res.status_code == 200:
            response_json = res.json()
            if response_json.get("success") is True:
                return response_json.get("quantity")
            else:
                print(f"Call to /stock/read for {book_id} was 200 but reported failure: {response_json.get('message')}")
                return None
        elif res.status_code == 415:
             print(f"CRITICAL: Received 415 Unsupported Media Type for GET /stock/read?book_id={book_id}. Check Orchestrator endpoint.")
             print(f"Response text: {res.text}")
             return None
        print(f"Error getting stock for {book_id}: HTTP {res.status_code} - {res.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"RequestException getting stock for {book_id}: {e}")
        return None
    except ValueError as e:
        print(f"ValueError (JSON decode failed) getting stock for {book_id}: {e}. Response text: {res.text if 'res' in locals() else 'N/A'}")
        return None

# --- Helper to increment stock (via Orchestrator's test endpoint) ---
def increment_book_stock(book_id: str, amount: int):
    """Uses the orchestrator's /stock/increment endpoint to add stock for testing purposes."""
    try:
        payload = {"book_id": book_id, "amount": amount}
        res = requests.post(f"{ORCHESTRATOR_URL}/stock/increment", json=payload, timeout=15) # Increased timeout
        if res.status_code == 200:
            response_json = res.json()
            if response_json.get("status") == "Success":
                print(f"Successfully incremented {book_id} by {amount}. New quantity: {response_json.get('new_quantity')}")
                return response_json.get("new_quantity")
            else:
                print(f"Call to /stock/increment for {book_id} was 200 but reported failure: {response_json.get('message')}")
                return None
        elif res.status_code == 415:
             print(f"CRITICAL: Received 415 Unsupported Media Type for POST /stock/increment with book_id={book_id}.")
             print(f"Response text: {res.text}")
             return None
        print(f"Error incrementing stock for {book_id}: HTTP {res.status_code} - {res.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"RequestException incrementing stock for {book_id}: {e}")
        return None
    except ValueError as e:
        print(f"ValueError (JSON decode failed) incrementing stock for {book_id}: {e}. Response text: {res.text if 'res' in locals() else 'N/A'}")
        return None

# --- Standard Valid Payload Generator ---
def create_base_payload(items_list, user_details=None, cc_details=None, unique_id_for_cc_suffix=None):
    """Creates a base order payload. Generates a slightly varied CC number if unique_id_for_cc_suffix is provided."""
    user = user_details or {"name": "Ahmed Wael97", "contact": "ahmedwael97@gmail.com".format(uuid.uuid4().hex[:4])}
    
    if cc_details:
        cc = cc_details
    else:
        base_cc_num_prefix = "41111111" # Start of a common pattern
        # Generate last 8 digits, allowing for some uniqueness to avoid simple velocity checks
        # while keeping a somewhat valid-looking structure for basic format checks.
        if unique_id_for_cc_suffix:
            # Ensure suffix is numeric and padded if necessary
            numeric_suffix_part = "".join(filter(str.isdigit, str(unique_id_for_cc_suffix)))
            # Take last 8 digits, or pad with random if too short, or truncate if too long
            if len(numeric_suffix_part) >= 8:
                final_suffix = numeric_suffix_part[-8:]
            else:
                needed_random_digits = 8 - len(numeric_suffix_part)
                random_part = "".join([str(random.randint(0,9)) for _ in range(needed_random_digits)])
                final_suffix = numeric_suffix_part + random_part
        else:
            final_suffix = "".join([str(random.randint(0,9)) for _ in range(8)])
            
        cc_number = base_cc_num_prefix + final_suffix
        cc = {"number": cc_number, "expirationDate": "12/2029", "cvv": str(random.randint(100,999))}
        
    return {
        "items": items_list,
        "user": user,
        "creditCard": cc,
        "billingAddress": {"street": "123 Test St", "city": "Testville", "state": "TS", "zip": "12345", "country": "USA"},
        "shippingMethod": "standard",
        "giftWrapping": False,
        "termsAndConditionsAccepted": True
    }

# --- Function to submit an order (used by concurrent tests) ---
def submit_order_task(payload):
    """Submits a single order payload to the /checkout endpoint and returns the result."""
    item_name_for_log = "UnknownItem"
    if payload.get("items") and len(payload["items"]) > 0:
        item_name_for_log = payload["items"][0].get("name", "UnnamedItem")
    
    try:
        print(f"Submitting order for: {item_name_for_log}, CC ending: ...{payload.get('creditCard',{}).get('number', '????')[-4:]}, Payload: {str(payload)[:150]}...")
        response = requests.post(f"{ORCHESTRATOR_URL}/checkout", json=payload, timeout=25) # Increased timeout further
        return {"status_code": response.status_code, "json": response.json(), "payload_name": item_name_for_log}
    except requests.exceptions.Timeout:
        print(f"Timeout submitting order for: {item_name_for_log}")
        return {"error": "Timeout", "payload_name": item_name_for_log}
    except Exception as e:
        print(f"Exception submitting order for {item_name_for_log}: {e}")
        return {"error": str(e), "payload_name": item_name_for_log}

# --- Test Definitions ---

@pytest.fixture(scope="session", autouse=True)
def clear_fraud_cache_globally(request):
    """
    This fixture attempts to "reset" the global fraud velocity cache before tests run.
    It does this by sending a few known "bad" (but unique) card numbers through the system
    to potentially fill up and flush older entries from the Fraud Detection's in-memory cache.
    This is a HACK and depends on the specifics of FRAUD_ATTEMPT_CACHE and MAX_ATTEMPTS_THRESHOLD.
    A proper reset would require an API endpoint on the Fraud Detection service.
    """
    print("\nAttempting to clear/cycle global fraud velocity cache before tests...")
    # MAX_ATTEMPTS_THRESHOLD in fraud_detection is 5
    # Send > 5 requests with unique, deliberately invalid (format-wise) CCs
    # to try and push out any lingering entries from previous runs.
    # These should be rejected by TransactionVerification early.
    for i in range(7): 
        payload = create_base_payload(
            items_list=[{"name": "Cache Clear Item", "quantity": 1}],
            cc_details={"number": f"100000000000000{i}", "expirationDate": "01/25", "cvv": "000"} # Invalid format CC
        )
        try:
            requests.post(f"{ORCHESTRATOR_URL}/checkout", json=payload, timeout=5)
        except:
            pass # We don't care about the response, just sending requests
    print("Fraud cache cycling attempt complete.")
    time.sleep(2) # Small pause

def test_single_non_fraudulent_order():
    item_name = "Clean Code"
    book_id = BOOK_MAPPINGS[item_name]
    quantity_to_order = 1

    print(f"\n--- Running Test: test_single_non_fraudulent_order ({item_name}) ---")

    initial_stock = get_book_stock(book_id)
    if initial_stock is None:
        pytest.fail(f"Could not get initial stock for {book_id} ({item_name}). Ensure Orchestrator's /stock/read and DB are working.")

    initial_stock_for_this_test_run = initial_stock
    if initial_stock < quantity_to_order:
        increment_needed = quantity_to_order - initial_stock
        print(f"Initial stock for {book_id} is {initial_stock}. Incrementing by {increment_needed} for test setup.")
        current_stock_after_increment = increment_book_stock(book_id, increment_needed)
        if current_stock_after_increment is None or current_stock_after_increment < quantity_to_order:
            pytest.fail(f"Failed to ensure enough stock for {book_id}. Needed {quantity_to_order}, have {current_stock_after_increment}.")
        initial_stock_for_this_test_run = current_stock_after_increment
        time.sleep(7) # Allow time for increment replication to settle
    
    print(f"Stock for {book_id} before test order: {initial_stock_for_this_test_run}")

    payload = create_base_payload(items_list=[{"name": item_name, "quantity": quantity_to_order}], unique_id_for_cc_suffix="single")
    result = submit_order_task(payload)

    assert "error" not in result, f"Order submission failed: {result.get('error')}"
    assert result["status_code"] == 200, f"Expected HTTP 200, got {result['status_code']}. Response: {result.get('json')}"
    response_data = result["json"]
    assert response_data["status"] == "Order Approved", f"Order status was '{response_data['status']}', expected 'Order Approved'. Msg: {response_data.get('message', 'N/A')}"
    assert "queued for processing" in response_data.get("message", "").lower()
    order_id = response_data["orderId"]
    print(f"Order {order_id} (for {item_name}) approved by orchestrator and queued.")

    print("Waiting 10s for backend processing (2PC, replication)...")
    time.sleep(10) # Increased further for single order processing

    final_stock = get_book_stock(book_id)
    if final_stock is None:
        pytest.fail(f"Could not get final stock for {book_id} ({item_name}) after order processing.")
    
    expected_final_stock = initial_stock_for_this_test_run - quantity_to_order
    assert final_stock == expected_final_stock, \
        f"Stock for {book_id} ({item_name}) did not decrement as expected. " \
        f"Initial for this test run: {initial_stock_for_this_test_run}, Ordered: {quantity_to_order}, " \
        f"Expected final: {expected_final_stock}, Actual final: {final_stock}"
    
    print(f"SUCCESS: test_single_non_fraudulent_order for {item_name}. Initial stock for test: {initial_stock_for_this_test_run}, Final stock: {final_stock}")

def test_multiple_non_conflicting_orders():
    print(f"\n--- Running Test: test_multiple_non_conflicting_orders ---")
    orders_config = [
        {"item_name": "Clean Code", "qty": 1, "id_suffix": "multi_ca"},
        {"item_name": "Pragmatic Programmer", "qty": 1, "id_suffix": "multi_pp"},
        {"item_name": "Design Patterns", "qty": 1, "id_suffix": "multi_dp"}
    ]
    for cfg in orders_config: cfg["book_id"] = BOOK_MAPPINGS[cfg["item_name"]]

    initial_stocks_for_this_test_run = {}
    for cfg in orders_config:
        stock = get_book_stock(cfg["book_id"])
        if stock is None: pytest.fail(f"Could not get stock for {cfg['book_id']} ({cfg['item_name']}).")
        initial_stocks_for_this_test_run[cfg["book_id"]] = stock # Record stock before potential increment
        if stock < cfg["qty"]:
            inc = cfg["qty"] - stock
            print(f"Stock for {cfg['book_id']} is {stock}. Incrementing by {inc} for test setup.")
            new_s = increment_book_stock(cfg["book_id"], inc)
            if new_s is None or new_s < cfg["qty"]: pytest.fail(f"Failed to ensure stock for {cfg['book_id']}.")
            initial_stocks_for_this_test_run[cfg["book_id"]] = new_s # Update with new stock
    print(f"Initial stocks for this test run: {initial_stocks_for_this_test_run}")
    time.sleep(7) # Allow increments to settle

    payloads = [create_base_payload(
                    items_list=[{"name": cfg["item_name"], "quantity": cfg["qty"]}],
                    unique_id_for_cc_suffix=cfg["id_suffix"]
                ) for cfg in orders_config]
    
    results = []
    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        futures = [executor.submit(submit_order_task, p) for p in payloads]
        for future in as_completed(futures):
            results.append(future.result())

    for res in results:
        payload_name = res.get('payload_name', 'Unknown Order')
        status_code = res.get('status_code', 'N/A')
        json_response = res.get('json', {})
        order_status = json_response.get('status', 'N/A')
        order_message = json_response.get('message', 'N/A')
        error_msg = res.get('error', 'N/A')
        print(f"Order for {payload_name}: Status Code {status_code}, Status {order_status}, Msg: {order_message}, Error {error_msg}")
        assert "error" not in res, f"Request for {payload_name} failed: {error_msg}"
        assert status_code == 200
        assert order_status == "Order Approved", f"Order for {payload_name} was '{order_status}', expected 'Order Approved'. Message: {order_message}"

    print("Waiting 15s for backend processing of multiple orders...")
    time.sleep(15) 

    for cfg in orders_config:
        final_stock = get_book_stock(cfg["book_id"])
        if final_stock is None: pytest.fail(f"Could not get final stock for {cfg['book_id']} ({cfg['item_name']}) post-test.")
        
        expected_stock = initial_stocks_for_this_test_run[cfg["book_id"]] - cfg["qty"]
        assert final_stock == expected_stock, \
            f"Stock for {cfg['book_id']} ({cfg['item_name']}) mismatch. " \
            f"Initial for test: {initial_stocks_for_this_test_run[cfg['book_id']]}, Expected: {expected_stock}, Got: {final_stock}"
    print("SUCCESS: test_multiple_non_conflicting_orders")

def test_multiple_mixed_orders():
    print(f"\n--- Running Test: test_multiple_mixed_orders ---")
    valid_item_name = "Clean Code" # Use a book that is likely to have stock
    valid_book_id = BOOK_MAPPINGS[valid_item_name]
    valid_qty = 1

    initial_stock_valid_item_for_test = get_book_stock(valid_book_id)
    if initial_stock_valid_item_for_test is None: pytest.fail(f"Failed to get stock for {valid_book_id} ({valid_item_name}).")
    if initial_stock_valid_item_for_test < valid_qty:
        inc = valid_qty - initial_stock_valid_item_for_test
        print(f"Stock for {valid_book_id} is {initial_stock_valid_item_for_test}. Incrementing by {inc} for test setup.")
        new_s = increment_book_stock(valid_book_id, inc)
        if new_s is None or new_s < valid_qty: pytest.fail(f"Failed to ensure stock for {valid_book_id}.")
        initial_stock_valid_item_for_test = new_s
    print(f"Stock for {valid_book_id} ({valid_item_name}) before mixed orders test: {initial_stock_valid_item_for_test}")
    time.sleep(7)

    payloads_config = [
        {"type": "valid_mixed", "payload": create_base_payload(items_list=[{"name": valid_item_name, "quantity": valid_qty}], unique_id_for_cc_suffix="mixed_valid_order")},
        # This CC number is too short (123), should be caught by TransactionVerification's VerifyCreditCardFormat
        {"type": "fraud_bad_cc_format", "payload": create_base_payload(items_list=[{"name": "Design Patterns", "quantity": 1}], cc_details={"number": "123", "expirationDate": "01/2028", "cvv": "111"}, unique_id_for_cc_suffix="mixed_fraud_cc_fmt")}
    ]

    results_map = {}
    with ThreadPoolExecutor(max_workers=len(payloads_config)) as executor:
        future_to_type = {executor.submit(submit_order_task, p_cfg["payload"]): p_cfg["type"] for p_cfg in payloads_config}
        for future in as_completed(future_to_type):
            order_type = future_to_type[future]
            results_map[order_type] = future.result()
    
    fraud_res = results_map["fraud_bad_cc_format"]
    print(f"Fraudulent Order (Bad CC Format) Result: {fraud_res}")
    assert "error" not in fraud_res, f"Fraudulent request (bad CC format) failed: {fraud_res.get('error')}"
    assert fraud_res["status_code"] == 200
    assert fraud_res["json"]["status"] == "Order Rejected", f"Fraudulent order (bad CC format) status was '{fraud_res['json'].get('status', 'N/A')}', expected 'Order Rejected'."
    assert "credit card format" in fraud_res["json"].get("message", "").lower() or "invalid credit card" in fraud_res["json"].get("message", "").lower()

    valid_res = results_map["valid_mixed"]
    print(f"Valid Order (in mixed test) Result: {valid_res}")
    assert "error" not in valid_res, f"Valid request (in mixed test) failed: {valid_res.get('error')}"
    assert valid_res["status_code"] == 200
    assert valid_res["json"]["status"] == "Order Approved", f"Valid order (in mixed test) status was '{valid_res['json'].get('status', 'N/A')}', expected 'Order Approved'. Message: {valid_res['json'].get('message', 'N/A')}"
    
    print("Waiting 20s for backend processing of valid order in mixed test...")
    time.sleep(20)

    final_stock_valid_item = get_book_stock(valid_book_id)
    if final_stock_valid_item is None: pytest.fail(f"Could not get final stock for {valid_book_id} ({valid_item_name}).")
    
    expected_final_stock_valid_item = initial_stock_valid_item_for_test - valid_qty
    assert final_stock_valid_item == expected_final_stock_valid_item, \
        f"Stock for {valid_book_id} ({valid_item_name}) mismatch. " \
        f"Initial for test: {initial_stock_valid_item_for_test}, Expected: {expected_final_stock_valid_item}, Got: {final_stock_valid_item}"
    print("SUCCESS: test_multiple_mixed_orders")

def test_conflicting_orders_limited_stock():
    print(f"\n--- Running Test: test_conflicting_orders_limited_stock ---")
    conflict_item_name = "Domain-Driven Design"
    conflict_book_id = BOOK_MAPPINGS[conflict_item_name]
    
    print(f"Setting up stock for {conflict_book_id} ({conflict_item_name}) to 1 for conflict test.")
    current_stock = get_book_stock(conflict_book_id)
    if current_stock is None: pytest.fail(f"Could not get stock for {conflict_book_id} to setup conflict test.")

    stock_after_setup = current_stock
    if current_stock == 0:
        stock_after_setup = increment_book_stock(conflict_book_id, 1)
    elif current_stock > 1:
        # This test is most effective if stock is exactly 1.
        # If you have a "set_stock" or "decrement_stock_direct" test API, use it here.
        # For now, we'll proceed but the number of "successful" 2PC commits will be current_stock.
        print(f"WARNING: Stock for {conflict_book_id} is {current_stock}. Decrementing to 1 for a clearer conflict test if possible.")
        # Attempt to decrement to 1, requires a decrement_stock API endpoint or adjust test expectations
        # This is a placeholder for a proper "set stock" operation.
        # For now, if you don't have a direct decrement, this part might not fully set it to 1.
        # We will proceed with current_stock if > 1.
        # A more advanced setup might involve a fixture to set DB state.
        # For this test to be very specific about ONE success, it's best if initial_stock_for_this_conflict_test = 1
        if current_stock > 1:
             print(f"Note: Cannot reliably set stock to 1 from {current_stock} without a direct DB manipulation or 'set_stock' API. Test will run with current stock.")
        # No change if current_stock is 1
    
    if stock_after_setup is None or stock_after_setup < 1 : # Try to make sure there's at least one.
        print(f"Stock for {conflict_book_id} is {stock_after_setup}. Attempting to ensure at least 1.")
        stock_after_setup = increment_book_stock(conflict_book_id, 1) # Make it 1 if it was 0 or increment failed
        if stock_after_setup is None or stock_after_setup < 1:
             pytest.fail(f"Failed to set stock of {conflict_book_id} to at least 1. Current: {stock_after_setup}")
    
    initial_stock_for_this_conflict_test = stock_after_setup # This is the actual stock available for conflicting orders
    print(f"Initial stock for {conflict_book_id} for conflict test: {initial_stock_for_this_conflict_test}")
    time.sleep(7) 

    # Send more orders than available stock
    num_orders_to_send = initial_stock_for_this_conflict_test + 2 
    print(f"Sending {num_orders_to_send} orders for {conflict_item_name} (available stock={initial_stock_for_this_conflict_test}).")
    payloads = [create_base_payload(
                    items_list=[{"name": conflict_item_name, "quantity": 1}],
                    unique_id_for_cc_suffix=f"conflict_{i}"
                ) for i in range(num_orders_to_send)]

    results = []
    with ThreadPoolExecutor(max_workers=num_orders_to_send) as executor:
        futures = [executor.submit(submit_order_task, p) for p in payloads]
        for future in as_completed(futures):
            results.append(future.result())

    orchestrator_approved_count = 0
    orchestrator_rejected_count = 0
    for i, res in enumerate(results):
        payload_name = res.get('payload_name', 'Unknown Order')
        status_code = res.get('status_code', 'N/A')
        json_response = res.get('json', {})
        order_status = json_response.get('status', 'N/A')
        order_message = json_response.get('message', 'N/A')
        print(f"Conflicting Order {i+1} ({payload_name}) Result: Code {status_code}, Status {order_status}, Msg: {order_message}, Error {res.get('error')}")
        if "error" not in res and status_code == 200:
            if order_status == "Order Approved":
                orchestrator_approved_count += 1
            elif order_status == "Order Rejected":
                orchestrator_rejected_count +=1
        else:
            print(f"WARNING: Conflicting order {i+1} had an unexpected submission error or status code: {res}")
    
    print(f"Orchestrator initially approved {orchestrator_approved_count} / {num_orders_to_send} conflicting orders.")
    print(f"Orchestrator initially rejected {orchestrator_rejected_count} / {num_orders_to_send} conflicting orders (likely due to concurrent validation effects like card velocity).")

    # Expect that only 'initial_stock_for_this_conflict_test' orders could *actually* go through 2PC if they were all approved by orchestrator.
    # If orchestrator_approved_count is less than initial_stock, then even fewer will make it to 2PC.
    # The number of orders that will *attempt* 2PC is min(orchestrator_approved_count, initial_stock_for_this_conflict_test) IF initial_stock > 0
    # No, the number of orders that will attempt 2PC is `orchestrator_approved_count`.
    # Out of those, at most `initial_stock_for_this_conflict_test` can succeed at the DB level.

    print("Waiting 20s for backend processing of conflicting orders...")
    time.sleep(20) 

    final_stock = get_book_stock(conflict_book_id)
    if final_stock is None: pytest.fail(f"Could not get final stock for {conflict_book_id} ({conflict_item_name}).")

    # The final stock should be 0 if there was any stock to begin with and at least one order was approved by orchestrator to attempt purchase.
    # If initial_stock_for_this_conflict_test was N, and orchestrator_approved_count was M,
    # then min(N, M) orders *could have* succeeded the 2PC. Stock would be initial - min(N,M).
    # However, due to sequential processing by single OE leader, only initial_stock_for_this_conflict_test can succeed.
    
    expected_final_stock_after_conflict = 0
    if initial_stock_for_this_conflict_test == 0 :
        expected_final_stock_after_conflict = 0
    elif orchestrator_approved_count == 0: # If no orders even made it past orchestrator validation
        expected_final_stock_after_conflict = initial_stock_for_this_conflict_test
    else: # Some orders were approved by orchestrator and attempted 2PC
        expected_final_stock_after_conflict = max(0, initial_stock_for_this_conflict_test - min(initial_stock_for_this_conflict_test, orchestrator_approved_count) )
        # More simply, if stock was N, and M orders (>N) were approved by orchestrator,
        # N orders will succeed 2PC, stock becomes 0.
        # If stock was N, and M orders (<=N) were approved by orchestrator,
        # M orders will succeed 2PC, stock becomes N-M.
        # So, if orchestrator_approved_count >= initial_stock_for_this_conflict_test, then stock should be 0.
        # If orchestrator_approved_count < initial_stock_for_this_conflict_test, then stock should be initial_stock - orchestrator_approved_count.
        if orchestrator_approved_count >= initial_stock_for_this_conflict_test:
             expected_final_stock_after_conflict = 0
        else: # fewer orders approved by orchestrator than available stock
             expected_final_stock_after_conflict = initial_stock_for_this_conflict_test - orchestrator_approved_count


    assert final_stock == expected_final_stock_after_conflict, \
        f"Stock for {conflict_book_id} ({conflict_item_name}) after conflict test is incorrect. " \
        f"Initial for test: {initial_stock_for_this_conflict_test}, Orchestrator approved: {orchestrator_approved_count}, " \
        f"Expected final: {expected_final_stock_after_conflict}, Actual final: {final_stock}."
    
    print(f"SUCCESS: test_conflicting_orders_limited_stock. Initial stock for test: {initial_stock_for_this_conflict_test}, Orchestrator Approved: {orchestrator_approved_count}, Final stock: {final_stock}.")
    print("Manual log check recommended for OE and DB Primary to confirm which orders were aborted due to insufficient stock during 2PC.")