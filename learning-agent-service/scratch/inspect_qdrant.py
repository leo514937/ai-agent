import os
from qdrant_client import QdrantClient

def main():
    client = QdrantClient(url="http://localhost:6333")
    print("Qdrant Collections:")
    collections = client.get_collections()
    for col in collections.collections:
        print(f"- {col.name}")

if __name__ == "__main__":
    main()
