import psycopg
import sys

print("Connecting to postgres database...")
try:
    conn = psycopg.connect("postgresql://postgres:postgres@127.0.0.1:5432/postgres")
    print("Successfully connected to 'postgres' database!")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT datname FROM pg_database;")
        dbs = [row[0] for row in cur.fetchall()]
        print("Available databases:", dbs)
        
        if "learning_agent" in dbs:
            print("'learning_agent' database exists!")
        else:
            print("'learning_agent' database does not exist. Creating it now...")
            cur.execute("CREATE DATABASE learning_agent;")
            print("'learning_agent' database created successfully!")
            
    conn.close()
    
    # Now try to connect to learning_agent
    conn = psycopg.connect("postgresql://postgres:postgres@127.0.0.1:5432/learning_agent")
    print("Successfully connected to 'learning_agent' database!")
    conn.close()
except Exception as e:
    print("Error during PostgreSQL connection/setup:", e, file=sys.stderr)
    sys.exit(1)
