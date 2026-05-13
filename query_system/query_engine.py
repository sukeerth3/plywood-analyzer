"""Core query engine for the demo and natural-language query interfaces."""

import os
import re
import json
import sqlite3
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False
from analysis.graph_importer import (
    SCHEMA_DDL as SQLITE_SCHEMA,
    _graph_from_dot_file,
    _demangle,
    _is_user_function,
)

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "plywood2026")
SQLITE_DB = os.getenv("SQLITE_DB", "data/coverage.db")

# Schema descriptions for natural-language prompts

NEO4J_SCHEMA = """
Neo4j Graph Schema:
  Nodes:
    (:Function {name: STRING})           -- program functions
    (:BasicBlock {id: STRING, function: STRING, label: STRING, instructions: STRING, line_count: INT})
    (:Variable {name: STRING, function: STRING})

  Relationships:
    (:Function)-[:CALLS]->(:Function)                      -- call graph edges
    (:Function)-[:ENTRY_BLOCK]->(:BasicBlock)              -- function entry points
    (:BasicBlock)-[:SUCCESSOR {condition: STRING}]->(:BasicBlock) -- CFG edges
    (:Variable)-[:DEPENDS_ON {type: STRING, callee: STRING?}]->(:Variable)  -- data dependency edges
"""


class QueryEngine:
    def __init__(self):
        self.project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.neo4j = None
        if GraphDatabase is not None:
            self.neo4j = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.sqlite = sqlite3.connect(SQLITE_DB)
        self.sqlite.row_factory = sqlite3.Row

    def _project_dir(self):
        return getattr(self, "project_dir", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _load_callgraph(self):
        dot_path = os.path.join(self._project_dir(), "build", "plywood_calc.ll.callgraph.dot")
        graphs = _graph_from_dot_file(dot_path)
        graph = graphs[0] if graphs else None
        if graph is None:
            return {}

        func_map = {}
        for node in graph.get_nodes():
            raw_label = node.get_label() or node.get_name()
            label = raw_label.strip('"').strip("{}").strip()
            clean = _demangle(label)
            if clean and _is_user_function(clean):
                func_map[node.get_name()] = clean

        adjacency = {name: set() for name in func_map.values()}
        for edge in graph.get_edges():
            src = edge.get_source()
            dst = edge.get_destination()
            if src in func_map and dst in func_map:
                adjacency.setdefault(func_map[src], set()).add(func_map[dst])
        return adjacency

    def _reachable_functions(self, start):
        adjacency = self._load_callgraph()
        seen = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(sorted(adjacency.get(node, []), reverse=True))
        return seen

    def _dependency_function_candidates(self, func):
        if func is None:
            return None
        dep_path = os.path.join(self._project_dir(), "data", "dependencies.json")
        candidates = {func}
        try:
            with open(dep_path) as f:
                deps = json.load(f)
        except OSError:
            return sorted(candidates)
        for dep in deps:
            raw = dep.get("function")
            if raw and _demangle(raw) == func:
                candidates.add(raw)
            callee = dep.get("callee")
            if callee and _demangle(callee) == func:
                candidates.add(callee)
        return sorted(candidates)

    def _function_matches(self, actual, expected):
        if expected is None:
            return True
        if actual is None:
            return False
        return actual == expected or _demangle(actual) == expected

    def _find_dependency_path(self, var_a, var_b, var_a_func=None, var_b_func=None):
        dep_path = os.path.join(self._project_dir(), "data", "dependencies.json")
        with open(dep_path) as f:
            deps = json.load(f)

        adjacency = {}
        nodes = set()
        for dep in deps:
            func = dep["function"]
            to_func = dep.get("callee") or func
            left = (dep["from"], func)
            right = (dep["to"], to_func)
            nodes.add(left)
            nodes.add(right)
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)

        starts = sorted(
            node for node in nodes
            if node[0] == var_a and self._function_matches(node[1], var_a_func)
        )
        targets = {
            node for node in nodes
            if node[0] == var_b and self._function_matches(node[1], var_b_func)
        }
        if not starts or not targets:
            return None

        queue = [(node, [node]) for node in starts]
        seen = set(starts)
        while queue:
            node, path = queue.pop(0)
            if node in targets:
                return path
            for nxt in sorted(adjacency.get(node, [])):
                if nxt in seen:
                    continue
                seen.add(nxt)
                queue.append((nxt, path + [nxt]))
        return None

    def close(self):
        if self.neo4j is not None:
            self.neo4j.close()
        self.sqlite.close()

    # Demo query 1: call graph traversal
    # "Where is function calculate_cuts called?"

    def demo_q1_callers(self, function_name="calculate_cuts"):
        """Find all callers of a given function using call graph traversal."""
        if self.neo4j is not None:
            cypher = """
            MATCH (caller:Function)-[:CALLS]->(target:Function {name: $fname})
            RETURN caller.name AS caller_function
            ORDER BY caller.name
            """
            with self.neo4j.session() as session:
                result = session.run(cypher, fname=function_name)
                callers = [record["caller_function"] for record in result]

            cypher2 = """
            MATCH (source:Function {name: $fname})-[:CALLS]->(callee:Function)
            RETURN callee.name AS callee_function
            ORDER BY callee.name
            """
            with self.neo4j.session() as session:
                result2 = session.run(cypher2, fname=function_name)
                callees = [record["callee_function"] for record in result2]
        else:
            callgraph = self._load_callgraph()
            callers = sorted(src for src, dsts in callgraph.items() if function_name in dsts)
            callees = sorted(callgraph.get(function_name, []))

        cypher_display = (
            "MATCH (caller:Function)-[:CALLS]->\n"
            "      (t:Function {name: $fname})\n"
            "RETURN caller.name AS caller_function\n"
            "ORDER BY caller.name\n\n"
            "MATCH (t:Function {name: $fname})-[:CALLS]->\n"
            "      (callee:Function)\n"
            "RETURN callee.name AS callee_function\n"
            "ORDER BY callee.name"
        )
        return {
            "query": f'Where is function {function_name} called?',
            "type": "call_graph",
            "function": function_name,
            "callers": callers,
            "callees": callees,
            "cypher": cypher_display,
            "answer": _format_caller_answer(function_name, callers, callees)
        }

    # Demo query 2: dependency path query
    # "Are variables board.length and rows_normal dependent?"

    def demo_q2_dependency(self, var_a="board.length", var_b="rows_normal",
                           var_a_func=None, var_b_func=None):
        """Check if two variables have a dependency path via DEPENDS_ON edges."""
        paths = []
        var_a_func_candidates = self._dependency_function_candidates(var_a_func)
        var_b_func_candidates = self._dependency_function_candidates(var_b_func)
        if self.neo4j is not None:
            cypher = """
            MATCH (a:Variable {name: $va}), (b:Variable {name: $vb})
            WHERE ($vaf IS NULL OR a.function IN $vaf)
              AND ($vbf IS NULL OR b.function IN $vbf)
            MATCH p = shortestPath(
                (a)-[:DEPENDS_ON*1..10]-(b)
            )
            RETURN [n in nodes(p) | n.name] AS path,
                   [n in nodes(p) | n.function] AS functions,
                   length(p) AS depth
            ORDER BY depth
            LIMIT 5
            """
            with self.neo4j.session() as session:
                try:
                    result = session.run(
                        cypher,
                        va=var_a,
                        vb=var_b,
                        vaf=var_a_func_candidates,
                        vbf=var_b_func_candidates,
                    )
                    for record in result:
                        paths.append({
                            "nodes": record["path"],
                            "functions": [_demangle(f) or f for f in record["functions"]],
                            "depth": record["depth"]
                        })
                except Exception:
                    cypher_fallback = """
                    MATCH (a:Variable {name: $va}), (b:Variable {name: $vb})
                    WHERE ($vaf IS NULL OR a.function IN $vaf)
                      AND ($vbf IS NULL OR b.function IN $vbf)
                    MATCH p = (a)-[:DEPENDS_ON*1..5]->(b)
                    RETURN [n in nodes(p) | n.name] AS path,
                           [n in nodes(p) | n.function] AS functions,
                           length(p) AS depth
                    ORDER BY depth
                    LIMIT 1
                    """
                    result = session.run(
                        cypher_fallback,
                        va=var_a,
                        vb=var_b,
                        vaf=var_a_func_candidates,
                        vbf=var_b_func_candidates,
                    )
                    for record in result:
                        paths.append({
                            "nodes": record["path"],
                            "functions": [_demangle(f) or f for f in record["functions"]],
                            "depth": record["depth"]
                        })
        else:
            fallback_path = self._find_dependency_path(var_a, var_b, var_a_func, var_b_func)
            if fallback_path:
                paths.append({
                    "nodes": [node[0] for node in fallback_path],
                    "functions": [_demangle(node[1]) or node[1] for node in fallback_path],
                    "depth": len(fallback_path) - 1
                })

        dependent = len(paths) > 0

        cypher_display = (
            "MATCH (a:Variable {name: $va}),\n"
            "      (b:Variable {name: $vb})\n"
            "WHERE ($vaf IS NULL OR a.function IN $vaf)\n"
            "  AND ($vbf IS NULL OR b.function IN $vbf)\n"
            "MATCH p = shortestPath(\n"
            "  (a)-[:DEPENDS_ON*1..10]-(b)\n"
            ")\n"
            "RETURN [n IN nodes(p) | n.name] AS path,\n"
            "       [n IN nodes(p) | n.function] AS functions,\n"
            "       length(p) AS depth\n"
            "ORDER BY depth\n"
            "LIMIT 5"
        )
        scope = []
        if var_a_func:
            scope.append(f"{var_a}@{var_a_func}")
        if var_b_func:
            scope.append(f"{var_b}@{var_b_func}")
        scope_suffix = f" scoped to {', '.join(scope)}" if scope else ""
        return {
            "query": f'Are variables {var_a} and {var_b} dependent{scope_suffix}?',
            "type": "dependency",
            "var_a": var_a,
            "var_b": var_b,
            "var_a_func": var_a_func,
            "var_b_func": var_b_func,
            "dependent": dependent,
            "paths": paths,
            "cypher": cypher_display,
            "answer": _format_dep_answer(var_a, var_b, dependent, paths)
        }

    # Demo query 3: uncovered gcov line-blocks
    # "Which functions reachable from main contain uncovered gcov line-blocks?"

    def demo_q3_uncovered(self):
        """
        Cross-analysis query: call graph reachability + coverage data.
        Finds functions reachable from main that have uncovered gcov line-blocks.
        """
        cypher = """
        MATCH (main:Function {name: 'main'})-[:CALLS*0..10]->(reachable:Function)
        RETURN DISTINCT reachable.name AS fname
        ORDER BY reachable.name
        """
        reachable = []
        if self.neo4j is not None:
            with self.neo4j.session() as session:
                result = session.run(cypher)
                reachable = [record["fname"] for record in result]
        else:
            reachable = sorted(self._reachable_functions("main"))

        cur = self.sqlite.cursor()
        uncovered_funcs = []
        coverage_sql = """
                WITH effective AS (
                    SELECT block_id, MAX(hit_count) AS hit_count
                    FROM coverage
                    WHERE function = ?
                    GROUP BY block_id
                )
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN hit_count = 0 THEN 1 ELSE 0 END) as uncovered,
                       GROUP_CONCAT(CASE WHEN hit_count = 0 THEN block_id END) as uncov_blocks
                FROM effective
            """

        for fname in reachable:
            cur.execute(coverage_sql, (fname,))
            row = cur.fetchone()

            uncovered_count = row[1] or 0 if row else 0
            if row and row[0] > 0 and uncovered_count > 0:
                uncov_blocks = row[2].split(",") if row[2] else []
                uncovered_funcs.append({
                    "function": fname,
                    "total_blocks": row[0],
                    "uncovered_blocks": uncovered_count,
                    "coverage_pct": round(100.0 * (row[0] - uncovered_count) / row[0], 1),
                    "block_ids": uncov_blocks[:10]  # Limit for display
                })

        cypher_display = (
            "MATCH (m:Function {name: 'main'})\n"
            "      -[:CALLS*0..10]->(f:Function)\n"
            "RETURN DISTINCT f.name AS fname\n"
            "ORDER BY f.name"
        )
        sql_display = coverage_sql.strip()
        return {
            "query": "Which functions reachable from main contain uncovered gcov line-blocks?",
            "type": "coverage_reachability",
            "reachable_functions": reachable,
            "uncovered_functions": uncovered_funcs,
            "cypher": cypher_display,
            "sql": sql_display,
            "answer": _format_uncovered_answer(reachable, uncovered_funcs)
        }

    # Demo query 4: tainted-input reach to uncovered scopes
    # "Which get_input-written variables flow into uncovered functions?"

    def demo_q4_taint_reach(self):
        """Find get_input-tainted variables that reach variables in uncovered scopes."""
        source_funcs = self._dependency_function_candidates("get_input")

        reachability_cypher = """
        MATCH (main:Function {name: 'main'})-[:CALLS*0..10]->(reachable:Function)
        RETURN DISTINCT reachable.name AS fname
        ORDER BY reachable.name
        """
        source_cypher = """
        MATCH (s:Variable)
        WHERE s.function IN $source_funcs
          AND EXISTS { MATCH (s)-[:DEPENDS_ON]-() }
        RETURN DISTINCT s.name AS source_var
        ORDER BY source_var
        """
        path_cypher = """
        MATCH (src:Variable {name: $source_var})
        WHERE src.function IN $source_funcs
        MATCH p = (src)-[:DEPENDS_ON*1..10]->(sink:Variable)
        WHERE sink.function IN $sink_funcs
        RETURN sink.name AS sink_var,
               [n IN nodes(p) | n.name] AS path_names,
               [n IN nodes(p) | n.function] AS path_functions,
               length(p) AS depth
        ORDER BY depth, sink_var
        LIMIT 25
        """
        uncovered_sql = """
        WITH effective AS (
            SELECT function, block_id, MAX(hit_count) AS hit_count
            FROM coverage
            GROUP BY function, block_id
        )
        SELECT function, COUNT(*) AS uncovered_blocks
        FROM effective
        WHERE hit_count = 0
        GROUP BY function
        ORDER BY function
        """

        sources = []
        reachable = set()
        if self.neo4j is not None:
            with self.neo4j.session() as session:
                reachable = {row["fname"] for row in session.run(reachability_cypher)}
                rows = session.run(source_cypher, source_funcs=source_funcs)
                sources = [row["source_var"] for row in rows]
        else:
            reachable = self._reachable_functions("main")
            sources = self._source_vars_from_dependencies(source_funcs)
        sources = _ordered_sources(sources)

        uncovered = {
            row["function"]: int(row["uncovered_blocks"])
            for row in self.sqlite.execute(uncovered_sql)
            if row["function"] in reachable
        }

        sink_results = []
        if self.neo4j is not None:
            with self.neo4j.session() as session:
                for sink_func, uncovered_blocks in uncovered.items():
                    sink_funcs = self._dependency_function_candidates(sink_func)
                    tainted = {}
                    example_path = None
                    for source_var in sources:
                        rows = session.run(
                            path_cypher,
                            source_var=source_var,
                            source_funcs=source_funcs,
                            sink_funcs=sink_funcs,
                        )
                        for row in rows:
                            sink_var = row["sink_var"]
                            tainted[sink_var] = True
                            if example_path is None:
                                example_path = _format_scoped_path(
                                    row["path_names"],
                                    row["path_functions"],
                                )
                    if tainted:
                        sink_results.append({
                            "function": sink_func,
                            "uncovered_blocks": uncovered_blocks,
                            "tainted_vars": sorted(tainted),
                            "example_path": example_path or [],
                        })
        else:
            sink_results = self._q4_dependency_fallback(sources, uncovered)

        cypher_display = (
            reachability_cypher.strip()
            + "\n\n"
            + source_cypher.strip()
            + "\n\n"
            + path_cypher.strip()
            + "\n\n"
            + f"-- params: source_funcs={source_funcs}, "
            + "source_var=<each source>, sink_funcs=<uncovered function candidates>"
        )
        return {
            "query": "Which input-tainted variables flow into functions with uncovered gcov line-blocks?",
            "type": "taint_reach",
            "sources": sources,
            "sinks": sink_results,
            "cypher": cypher_display,
            "sql": uncovered_sql.strip(),
            "answer": _format_taint_answer(sources, uncovered, sink_results),
        }

    def _source_vars_from_dependencies(self, source_funcs):
        dep_path = os.path.join(self._project_dir(), "data", "dependencies.json")
        with open(dep_path) as f:
            deps = json.load(f)
        source_func_set = set(source_funcs or [])
        sources = set()
        for dep in deps:
            if dep.get("function") not in source_func_set:
                continue
            sources.add(dep.get("from"))
            sources.add(dep.get("to"))
        return [s for s in sources if s]

    def _q4_dependency_fallback(self, sources, uncovered):
        results = []
        for sink_func, uncovered_blocks in uncovered.items():
            tainted = {}
            example_path = None
            for source_var in sources:
                for sink_var in self._variables_for_function(sink_func):
                    path = self._find_dependency_path(
                        source_var,
                        sink_var,
                        var_a_func="get_input",
                        var_b_func=sink_func,
                    )
                    if not path:
                        continue
                    tainted[sink_var] = True
                    if example_path is None:
                        example_path = [
                            f"{name}@{_demangle(func) or func}"
                            for name, func in path
                        ]
            if tainted:
                results.append({
                    "function": sink_func,
                    "uncovered_blocks": uncovered_blocks,
                    "tainted_vars": sorted(tainted),
                    "example_path": example_path or [],
                })
        return results

    def _variables_for_function(self, function_name):
        dep_path = os.path.join(self._project_dir(), "data", "dependencies.json")
        with open(dep_path) as f:
            deps = json.load(f)
        variables = set()
        for dep in deps:
            if self._function_matches(dep.get("function"), function_name):
                variables.add(dep.get("from"))
            if self._function_matches(dep.get("callee"), function_name):
                variables.add(dep.get("to"))
            if self._function_matches(dep.get("function"), function_name):
                variables.add(dep.get("to"))
        return sorted(v for v in variables if v)

    # Natural-language query path

    def nl_query(self, question):
        """Handle a natural-language query by selecting a backend and running it."""
        try:
            import anthropic
        except ImportError:
            return {"error": "anthropic package not installed. Run: pip install anthropic"}

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return {"error": "ANTHROPIC_API_KEY not set. Add it to .env"}

        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = f"""You are a program analysis query translator.
Given a natural language question about a C++ program's structure, generate
either a Cypher query (for Neo4j graph questions) or a SQL query (for coverage/testing data).

{NEO4J_SCHEMA}
{SQLITE_SCHEMA}

Respond in JSON format:
{{"backend": "neo4j" or "sqlite", "query": "<the generated query>", "explanation": "<brief explanation>"}}

Only output valid JSON. No markdown fences."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": question}]
        )

        response_text = message.content[0].text.strip()
        # Strip markdown fences if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            return {"error": f"Failed to parse LLM response: {response_text}"}

        backend = parsed.get("backend", "neo4j")
        query = parsed.get("query", "")
        explanation = parsed.get("explanation", "")

        if backend == "neo4j":
            return self._exec_cypher(query, question, explanation)
        elif backend == "sqlite":
            return self._exec_sql(query, question, explanation)
        else:
            return {"error": f"Unknown backend: {backend}"}

    def _exec_cypher(self, cypher, question, explanation):
        """Execute a Cypher query against Neo4j."""
        try:
            with self.neo4j.session() as session:
                result = session.run(cypher)
                records = [dict(r) for r in result]
            return {
                "query": question,
                "type": "nl_cypher",
                "cypher": cypher,
                "explanation": explanation,
                "results": records,
                "count": len(records)
            }
        except Exception as e:
            return {"error": f"Cypher execution failed: {str(e)}", "cypher": cypher}

    def _exec_sql(self, sql, question, explanation):
        """Execute a SQL query against SQLite."""
        try:
            cur = self.sqlite.cursor()
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            return {
                "query": question,
                "type": "nl_sql",
                "sql": sql,
                "explanation": explanation,
                "results": rows,
                "count": len(rows)
            }
        except Exception as e:
            return {"error": f"SQL execution failed: {str(e)}", "sql": sql}


# Answer formatters

def _format_caller_answer(fname, callers, callees):
    if not callers:
        answer = f"Function '{fname}' is not called by any other function in the program."
    else:
        caller_list = ", ".join(callers)
        answer = f"Function '{fname}' is called by: {caller_list}."

    if callees:
        callee_list = ", ".join(callees)
        answer += f" It in turn calls: {callee_list}."

    return answer


def _format_dep_answer(var_a, var_b, dependent, paths):
    if not dependent:
        return f"No dependency path found between '{var_a}' and '{var_b}'."

    path_str = " -> ".join(paths[0]["nodes"]) if paths else ""
    answer = f"Yes, '{var_a}' and '{var_b}' are dependent."
    if path_str:
        answer += f" Shortest path: {path_str} (depth {paths[0]['depth']})."
    return answer


def _format_uncovered_answer(reachable, uncovered_funcs):
    answer = f"{len(reachable)} functions are reachable from main. "

    if not uncovered_funcs:
        answer += "All reachable functions have full gcov line-block coverage."
    else:
        answer += f"{len(uncovered_funcs)} contain uncovered gcov line-blocks:\n"
        for uf in uncovered_funcs:
            answer += (f"  - {uf['function']}: {uf['uncovered_blocks']}/{uf['total_blocks']} "
                       f"line-blocks uncovered ({uf['coverage_pct']}% covered)\n")

    return answer


def _ordered_sources(sources):
    preferred = ["board.length", "board.width", "cut.length", "cut.width", "board", "cut"]
    source_set = set(sources)
    ordered = [s for s in preferred if s in source_set]
    ordered.extend(sorted(source_set - set(ordered)))
    return ordered


def _format_scoped_path(names, functions):
    return [
        f"{name}@{_demangle(func) or func}"
        for name, func in zip(names or [], functions or [])
    ]


def _format_taint_answer(sources, uncovered, sinks):
    if not sources:
        return "No get_input-tainted source variables were found in the dependency graph."
    if not uncovered:
        return "No functions currently contain uncovered gcov line-blocks."
    if not sinks:
        funcs = ", ".join(sorted(uncovered))
        return (
            f"Found get_input sources and uncovered scope(s): {funcs}, but no actual "
            "DEPENDS_ON path connects them. This surfaces a system limitation: the "
            "static extractor does not currently capture cross-function data flow "
            "for struct-by-value parameters."
        )

    parts = []
    for sink in sinks:
        vars_text = ", ".join(sink["tainted_vars"])
        parts.append(f"{sink['function']} receives tainted vars: {vars_text}.")
    return " ".join(parts)
