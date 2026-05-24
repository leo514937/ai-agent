import os
from dotenv import load_dotenv
from openai import OpenAI

def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("LEARNING_AGENT_OPENAI_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    
    print(f"Connecting to OpenAI API at {base_url}...")
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    try:
        response = client.embeddings.create(
            model=model,
            input="test string"
        )
        vector = response.data[0].embedding
        print(f"Successfully generated embedding vector of length: {len(vector)}")
    except Exception as e:
        print(f"Error generating embedding: {e}")

if __name__ == "__main__":
    main()
