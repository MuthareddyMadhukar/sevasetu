# -*- coding: utf-8 -*-
"""
Sewa Setu - CLI Evaluation Suite Runner.
Runs all persona evaluations against the live PostgreSQL database and MCP servers,
prints a structured summary table, and verifies database integrity.
"""

import sys
import os
import json

# Ensure app directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(BASE_DIR, "app")
sys.path.insert(0, APP_DIR)

from eval_framework import eval_runner, PERSONAS


def main():
    print("=" * 78)
    print("  SEWA SETU AGENT EVALUATION SUITE")
    print("  Department of Social Welfare, Government of Purvanchal")
    print("=" * 78)
    print(f"Loaded {len(PERSONAS)} personas (Citizen & Officer workflows).\n")

    report = eval_runner.run_all()
    summary = report["summary"]
    results = report["results"]

    print("\n" + "-" * 78)
    print(f"{'PERSONA':<24} | {'ROLE':<18} | {'STATUS':<8} | {'TIME (s)':<8}")
    print("-" * 78)

    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        time_str = f"{r.get('duration_seconds', 0.0):.2f}"
        role_short = r["role"].split("(")[0].strip()
        print(f"{r['name']:<24} | {role_short:<18} | {status_str:<8} | {time_str:<8}")

        for v in r["db_verifications"]:
            mark = "  [✓]" if v["passed"] else "  [✗]"
            print(f"   {mark} {v['assertion']}")
            if v.get("detail"):
                print(f"       Detail: {v['detail']}")
        print()

    print("=" * 78)
    print(f"EVALUATION SUMMARY:")
    print(f"  Total Personas: {summary['total']}")
    print(f"  Passed:         {summary['passed']}")
    print(f"  Failed:         {summary['failed']}")
    print(f"  Pass Rate:      {summary['pass_rate']}%")
    print(f"  Timestamp:      {summary['timestamp']}")
    print("=" * 78)

    if summary["failed"] > 0:
        sys.exit(1)
    else:
        print("\nAll evaluations passed successfully! Database states verified.")
        sys.exit(0)


if __name__ == "__main__":
    main()
