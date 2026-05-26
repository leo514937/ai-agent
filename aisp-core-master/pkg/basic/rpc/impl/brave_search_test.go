package impl

import (
	"context"
	"testing"
	"time"
)

// go test /data/apps/aisp-core/pkg/basic/rpc/impl -run TestBraveSearch
// dlv test /data/apps/aisp-core/pkg/basic/rpc/impl --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestBraveSearch
func TestBraveSearch(t *testing.T) {
	client := NewBraveSearchClient()
	ctx := context.Background()

	// Test case 1: Normal search
	t.Run("normal search", func(t *testing.T) {
		results, err := client.Search(ctx, "brave search", 5)
		if err != nil {
			t.Fatalf("Search failed: %v", err)
		}

		if len(results) == 0 {
			t.Error("Expected at least one result")
		}

		// Check result structure
		for i, result := range results {
			if result.Name == "" {
				t.Errorf("Result %d: Title is empty", i)
			}
			if result.Snippet == "" {
				t.Errorf("Result %d: Description is empty", i)
			}
			if result.Url == "" {
				t.Errorf("Result %d: URL is empty", i)
			}
		}
	})

	// Test case 2: Context cancellation
	t.Run("context cancellation", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(ctx, 1*time.Millisecond)
		defer cancel()

		_, err := client.Search(ctx, "brave search", 5)
		if err == nil {
			t.Error("Expected error due to context cancellation")
		}
	})

	// Test case 3: TopK limit
	t.Run("topk limit", func(t *testing.T) {
		results, err := client.Search(ctx, "brave search", 2)
		if err != nil {
			t.Fatalf("Search failed: %v", err)
		}

		if len(results) > 2 {
			t.Errorf("Expected maximum 2 results, got %d", len(results))
		}
	})

	// Test case 4: Empty query
	t.Run("empty query", func(t *testing.T) {
		_, err := client.Search(ctx, "", 5)
		if err == nil {
			t.Error("Expected error for empty query")
		}
	})
}
