#!/usr/bin/env python3
"""
Evaluation runner for CI pipeline.
Runs golden case evaluation and outputs results in CI-friendly format.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from learning_agent_service.local_life.eval.run_golden_cases import run_evaluation


def main():
    """Run evaluation and output results."""
    print("=" * 60)
    print("Running Golden Case Evaluation")
    print("=" * 60)

    try:
        results = run_evaluation()

        # Output summary
        print(f"\nTotal cases: {results.get('total', 0)}")
        print(f"Passed: {results.get('passed', 0)}")
        print(f"Failed: {results.get('failed', 0)}")
        print(f"Pass rate: {results.get('pass_rate', 0):.1%}")

        # Output failure details
        if results.get('failures'):
            print("\nFailed cases:")
            for failure in results['failures']:
                print(f"  - {failure.get('case_id')}: {failure.get('reason')}")

        # Exit with appropriate code
        if results.get('failed', 0) > 0:
            print("\n❌ Evaluation FAILED")
            sys.exit(1)
        else:
            print("\n✅ Evaluation PASSED")
            sys.exit(0)

    except Exception as e:
        print(f"\n❌ Evaluation ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
