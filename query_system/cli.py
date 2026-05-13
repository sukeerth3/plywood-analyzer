"""Command-line interface for the plywood analyzer query system."""

import sys
import json
import argparse
from query_system.query_engine import QueryEngine


def main():
    parser = argparse.ArgumentParser(
        description="Plywood Analyzer Query System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Demo queries (use --demo 1/2/3/4):
  1: Where is function calculate_cuts called?
  2: Are variables board.length and rows_normal dependent?
  3: Which functions reachable from main contain uncovered gcov line-blocks?
  4: Which input-tainted variables flow into uncovered functions?

Natural language (use --ask "your question"):
  Translates to Cypher or SQL through the configured query API.
        """
    )
    parser.add_argument("--demo", type=int, choices=[1, 2, 3, 4],
                        help="Run a demo query (1, 2, 3, or 4)")
    parser.add_argument("--ask", type=str,
                        help="Ask a natural language question")
    parser.add_argument("--func", type=str, default="calculate_cuts",
                        help="Function name for demo Q1 (default: calculate_cuts)")
    parser.add_argument("--var-a", type=str, default="board.length",
                        help="First variable for demo Q2 (default: board.length)")
    parser.add_argument("--var-b", type=str, default="rows_normal",
                        help="Second variable for demo Q2 (default: rows_normal)")
    parser.add_argument("--var-a-func", type=str, default=None,
                        help="Optional function scope for --var-a in demo Q2")
    parser.add_argument("--var-b-func", type=str, default=None,
                        help="Optional function scope for --var-b in demo Q2")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON instead of formatted text")

    args = parser.parse_args()

    if not args.demo and not args.ask:
        parser.print_help()
        sys.exit(1)

    engine = QueryEngine()

    try:
        if args.demo == 1:
            result = engine.demo_q1_callers(args.func)
        elif args.demo == 2:
            result = engine.demo_q2_dependency(
                args.var_a,
                args.var_b,
                var_a_func=args.var_a_func,
                var_b_func=args.var_b_func,
            )
        elif args.demo == 3:
            result = engine.demo_q3_uncovered()
        elif args.demo == 4:
            result = engine.demo_q4_taint_reach()
        elif args.ask:
            result = engine.nl_query(args.ask)
        else:
            result = {"error": "No query specified."}

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_formatted(result)

    finally:
        engine.close()


def _print_formatted(result):
    """Pretty-print a query result."""
    if "error" in result:
        print(f"\n  Error: {result['error']}")
        if "cypher" in result:
            print(f"  Generated Cypher: {result['cypher']}")
        if "sql" in result:
            print(f"  Generated SQL: {result['sql']}")
        return

    print(f"\n  Query: {result['query']}")
    print(f"  Type:  {result['type']}")
    print()

    if "answer" in result:
        print(f"  {result['answer']}")
        print()

    qtype = result.get("type", "")

    if qtype == "call_graph":
        if result.get("callers"):
            print("  Callers:")
            for c in result["callers"]:
                print(f"    -> {c}")
        if result.get("callees"):
            print("  Callees:")
            for c in result["callees"]:
                print(f"    <- {c}")

    elif qtype == "dependency":
        if result.get("paths"):
            print("  Dependency paths:")
            for p in result["paths"]:
                print(f"    {' -> '.join(p['nodes'])}  (depth {p['depth']})")

    elif qtype == "coverage_reachability":
        if result.get("uncovered_functions"):
            print("  Uncovered functions:")
            for uf in result["uncovered_functions"]:
                bar = _coverage_bar(uf["coverage_pct"])
                print(f"    {uf['function']:30s} {bar} {uf['coverage_pct']:5.1f}%  "
                      f"({uf['uncovered_blocks']}/{uf['total_blocks']} uncovered)")

    elif qtype == "taint_reach":
        print("  Sources:")
        for source in result.get("sources", []):
            print(f"    -> {source}")
        if result.get("sinks"):
            print("  Sinks:")
            for sink in result["sinks"]:
                print(f"    {sink['function']}: {', '.join(sink['tainted_vars'])}")
                if sink.get("example_path"):
                    print(f"      path: {' -> '.join(sink['example_path'])}")
        else:
            print("  Sinks: []")

    elif qtype in ("nl_cypher", "nl_sql"):
        if result.get("explanation"):
            print(f"  Explanation: {result['explanation']}")
        if result.get("cypher"):
            print(f"  Cypher: {result['cypher']}")
        if result.get("sql"):
            print(f"  SQL: {result['sql']}")
        if result.get("results"):
            print(f"\n  Results ({result['count']} rows):")
            for r in result["results"][:20]:
                print(f"    {r}")


def _coverage_bar(pct, width=20):
    """Generate a simple ASCII coverage bar."""
    filled = int(pct / 100 * width)
    return f"[{'#' * filled}{'.' * (width - filled)}]"


if __name__ == "__main__":
    main()
