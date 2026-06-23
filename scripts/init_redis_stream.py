import redis

try:
    # Connect to local Redis on default port 6379
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    try:
        # Create stream 'stream.orders' and group 'g1' starting from ID '0'
        r.xgroup_create('stream.orders', 'g1', id='0', mkstream=True)
        print("Successfully created Redis Stream 'stream.orders' and Consumer Group 'g1'.")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print("Consumer Group 'g1' already exists in Stream 'stream.orders'.")
        else:
            raise e
except Exception as e:
    print(f"Error connecting to Redis or initializing stream: {e}")
