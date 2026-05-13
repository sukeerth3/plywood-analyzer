"""Imports LLVM graph and coverage artifacts into Neo4j and SQLite."""

import os
import re
import sqlite3
import json
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

try:
    import pydot  # type: ignore
except ImportError:
    pydot = None

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "plywood2026")
SQLITE_DB = os.getenv("SQLITE_DB", "data/coverage.db")

SCHEMA_DDL = """CREATE TABLE IF NOT EXISTS coverage (
    function TEXT NOT NULL,
    block_id TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    hit_count INTEGER DEFAULT 0,
    branch_taken INTEGER DEFAULT NULL,
    source TEXT DEFAULT 'unknown',
    PRIMARY KEY (block_id, source)
);

CREATE TABLE IF NOT EXISTS test_cases (
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    board_l INTEGER,
    board_w INTEGER,
    cut_l INTEGER,
    cut_w INTEGER,
    expected_pieces INTEGER,
    actual_pieces INTEGER,
    passed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (name, source)
);

CREATE TABLE IF NOT EXISTS fuzz_stats (
    source TEXT NOT NULL PRIMARY KEY,
    total_execs INTEGER,
    execs_per_sec REAL,
    unique_crashes INTEGER,
    unique_hangs INTEGER,
    paths_total INTEGER,
    paths_found INTEGER,
    corpus_count INTEGER,
    run_time_seconds REAL,
    afl_replay_count INTEGER DEFAULT 0,
    afl_replay_blocks_added INTEGER DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""


class _DotNode:
    def __init__(self, name, label=None):
        self._name = name
        self._label = label

    def get_name(self):
        return self._name

    def get_label(self):
        return self._label


class _DotEdge:
    def __init__(self, source, destination, label=None):
        self._source = source
        self._destination = destination
        self._label = label

    def get_source(self):
        return self._source

    def get_destination(self):
        return self._destination

    def get_label(self):
        return self._label


class _DotGraph:
    def __init__(self, nodes, edges):
        self._nodes = nodes
        self._edges = edges

    def get_nodes(self):
        return self._nodes

    def get_edges(self):
        return self._edges


def _graph_from_dot_file(dot_path):
    if pydot is not None:
        return pydot.graph_from_dot_file(dot_path)
    return [_parse_dot_file(dot_path)]


class Neo4jImporter:
    def __init__(self):
        self.driver = None
        if GraphDatabase is not None:
            self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    def close(self):
        if self.driver is not None:
            self.driver.close()

    def clear_database(self):
        if self.driver is None:
            print("[neo4j] Driver unavailable; skipping database clear.")
            return
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("[neo4j] Database cleared.")

    def create_indexes(self):
        if self.driver is None:
            print("[neo4j] Driver unavailable; skipping index creation.")
            return
        with self.driver.session() as session:
            session.run("CREATE INDEX IF NOT EXISTS FOR (f:Function) ON (f.name)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (b:BasicBlock) ON (b.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (v:Variable) ON (v.name)")
            print("[neo4j] Indexes created.")

    # Call graph

    def import_callgraph(self, dot_path):
        """Parse a callgraph DOT file and import CALLS edges."""
        if self.driver is None:
            print("[callgraph] Neo4j driver unavailable; skipping graph import.")
            return
        graphs = _graph_from_dot_file(dot_path)
        if not graphs:
            print(f"[callgraph] No graph found in {dot_path}")
            return

        graph = graphs[0]
        func_map = {}

        for node in graph.get_nodes():
            raw_label = node.get_label() or node.get_name()
            label = raw_label.strip('"').strip("{}").strip()
            if not label or label in ("\\n", "Node0x", ""):
                continue
            clean = _demangle(label)
            if clean:
                func_map[node.get_name()] = clean

        # Filter to user-defined functions only
        user_funcs = {nid: fn for nid, fn in func_map.items() if _is_user_function(fn)}

        with self.driver.session() as session:
            for node_id, fname in user_funcs.items():
                session.run(
                    "MERGE (f:Function {name: $name})",
                    name=fname
                )

            edge_count = 0
            for edge in graph.get_edges():
                src = edge.get_source()
                dst = edge.get_destination()
                if src in user_funcs and dst in user_funcs:
                    session.run(
                        """
                        MATCH (a:Function {name: $src}), (b:Function {name: $dst})
                        MERGE (a)-[:CALLS]->(b)
                        """,
                        src=user_funcs[src],
                        dst=user_funcs[dst]
                    )
                    edge_count += 1

        print(f"[callgraph] Imported {len(user_funcs)} functions, {edge_count} call edges.")

    # Control flow graphs

    def import_cfg(self, dot_dir):
        """Parse per-function CFG DOT files and import SUCCESSOR edges."""
        if self.driver is None:
            print("[cfg] Neo4j driver unavailable; skipping graph import.")
            return
        dot_files = [f for f in os.listdir(dot_dir) if f.endswith(".dot")]
        total_blocks = 0
        total_edges = 0

        for dot_file in dot_files:
            # Extract function name from filename: .funcname.dot
            fname = dot_file.lstrip(".").replace(".dot", "")
            fname = _demangle(fname)
            if not fname:
                continue

            path = os.path.join(dot_dir, dot_file)
            graphs = _graph_from_dot_file(path)
            if not graphs:
                continue

            graph = graphs[0]
            block_map = {}

            with self.driver.session() as session:
                for node in graph.get_nodes():
                    node_name = node.get_name().strip('"')
                    label = node.get_label() or node_name
                    label = label.strip('"').strip("{}")

                    block_id = f"{fname}::{node_name}"
                    block_map[node.get_name()] = block_id

                    instructions = _extract_instructions(label)

                    session.run(
                        """
                        MERGE (b:BasicBlock {id: $id})
                        SET b.function = $func, b.label = $label,
                            b.instructions = $instr, b.line_count = $lc
                        """,
                        id=block_id,
                        func=fname,
                        label=label[:200],
                        instr=instructions,
                        lc=len(instructions.split("\n")) if instructions else 0
                    )
                    total_blocks += 1

                # Link function to its entry block
                if block_map:
                    first_block = list(block_map.values())[0]
                    session.run(
                        """
                        MATCH (f:Function {name: $func}), (b:BasicBlock {id: $bid})
                        MERGE (f)-[:ENTRY_BLOCK]->(b)
                        """,
                        func=fname,
                        bid=first_block
                    )

                for edge in graph.get_edges():
                    src = edge.get_source()
                    dst = edge.get_destination()
                    if src in block_map and dst in block_map:
                        edge_label = edge.get_label() or ""
                        session.run(
                            """
                            MATCH (a:BasicBlock {id: $src}), (b:BasicBlock {id: $dst})
                            MERGE (a)-[:SUCCESSOR {condition: $cond}]->(b)
                            """,
                            src=block_map[src],
                            dst=block_map[dst],
                            cond=edge_label.strip('"')
                        )
                        total_edges += 1

        print(f"[cfg] Imported {total_blocks} blocks, {total_edges} edges from {len(dot_files)} files.")

    # Data dependencies

    def import_dependencies(self, dep_file):
        """
        Import data dependency edges from a JSON file.
        Format: [{"from": "var_a", "to": "var_b", "function": "fname",
                  "type": "assignment|arithmetic|cross_call", "callee": "optional_fname"}]
        """
        if self.driver is None:
            print("[deps] Neo4j driver unavailable; skipping graph import.")
            return
        import json
        with open(dep_file) as f:
            deps = json.load(f)

        imported = 0
        skipped = 0
        with self.driver.session() as session:
            for dep in deps:
                from_var = dep.get("from")
                to_var = dep.get("to")
                if _is_numeric_dependency_name(from_var) or _is_numeric_dependency_name(to_var):
                    skipped += 1
                    continue
                dtype = dep.get("type", "unknown")
                callee = dep.get("callee")
                to_func = callee or dep["function"]
                session.run(
                    """
                    MERGE (a:Variable {name: $from_var, function: $func})
                    MERGE (b:Variable {name: $to_var, function: $to_func})
                    MERGE (a)-[r:DEPENDS_ON {type: $dtype}]->(b)
                    SET r.callee = $callee
                    """,
                    from_var=from_var,
                    to_var=to_var,
                    func=dep["function"],
                    to_func=to_func,
                    dtype=dtype,
                    callee=callee,
                )
                imported += 1

        if skipped:
            print(f"[deps] Imported {imported} dependency edges ({skipped} numeric endpoints skipped).")
        else:
            print(f"[deps] Imported {imported} dependency edges.")


def _is_numeric_dependency_name(name):
    if name is None:
        return True
    return str(name).lstrip("%").isdigit()


def _normalize_coverage_source(source):
    if source == "gcov":
        return "gcov_curated"
    return source or "unknown"


class SQLiteManager:
    """Manages coverage and test metadata in SQLite."""

    def __init__(self, db_path=None):
        self.db_path = db_path or SQLITE_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.create_tables()

    def create_tables(self):
        cur = self.conn.cursor()
        cur.executescript(SCHEMA_DDL)
        self._migrate_coverage_table()
        self._migrate_fuzz_stats_table()
        self._backfill_coverage_sources()
        cur.executescript("""
            CREATE INDEX IF NOT EXISTS idx_coverage_func ON coverage(function);
            CREATE INDEX IF NOT EXISTS idx_coverage_block ON coverage(block_id);
            CREATE INDEX IF NOT EXISTS idx_coverage_source ON coverage(source);
        """)
        self.conn.commit()

    def _create_tables(self):
        self.create_tables()

    def _migrate_coverage_table(self):
        """Move old block_id-primary-key coverage tables to source-scoped rows."""
        cur = self.conn.cursor()
        columns = cur.execute("PRAGMA table_info(coverage)").fetchall()
        pk_columns = [row[1] for row in sorted(columns, key=lambda r: r[5]) if row[5]]
        if pk_columns == ["block_id", "source"]:
            return

        cur.execute("ALTER TABLE coverage RENAME TO coverage_old")
        cur.execute("""
            CREATE TABLE coverage (
                function TEXT NOT NULL,
                block_id TEXT NOT NULL,
                line_start INTEGER,
                line_end INTEGER,
                hit_count INTEGER DEFAULT 0,
                branch_taken INTEGER DEFAULT NULL,
                source TEXT DEFAULT 'unknown',
                PRIMARY KEY (block_id, source)
            )
        """)
        old_columns = {row[1] for row in cur.execute("PRAGMA table_info(coverage_old)")}
        source_expr = (
            "CASE WHEN source = 'gcov' THEN 'gcov_curated' "
            "WHEN source IS NULL THEN 'unknown' ELSE source END"
            if "source" in old_columns
            else "'gcov_curated'"
        )
        branch_expr = "branch_taken" if "branch_taken" in old_columns else "NULL"
        cur.execute(f"""
            INSERT OR REPLACE INTO coverage
                (function, block_id, line_start, line_end, hit_count, branch_taken, source)
            SELECT function, block_id, line_start, line_end, hit_count,
                   {branch_expr}, {source_expr}
            FROM coverage_old
        """)
        cur.execute("DROP TABLE coverage_old")

    def _migrate_fuzz_stats_table(self):
        cur = self.conn.cursor()
        columns = {row[1] for row in cur.execute("PRAGMA table_info(fuzz_stats)")}
        if "afl_replay_count" not in columns:
            cur.execute("ALTER TABLE fuzz_stats ADD COLUMN afl_replay_count INTEGER DEFAULT 0")
        if "afl_replay_blocks_added" not in columns:
            cur.execute("ALTER TABLE fuzz_stats ADD COLUMN afl_replay_blocks_added INTEGER DEFAULT 0")

    def _backfill_coverage_sources(self):
        cur = self.conn.cursor()
        cur.execute("UPDATE coverage SET source = 'gcov_curated' WHERE source = 'gcov'")
        cur.execute("UPDATE coverage SET source = 'unknown' WHERE source IS NULL")

    def import_coverage_json(self, json_path, source=None):
        """Import gcov/lcov JSON coverage data."""
        with open(json_path) as f:
            data = json.load(f)

        cur = self.conn.cursor()
        self._backfill_coverage_sources()
        sources = sorted({
            _normalize_coverage_source(source or entry.get("source", "gcov_curated"))
            for entry in data
        })
        for src in sources:
            cur.execute("DELETE FROM coverage WHERE source = ?", (src,))
        count = 0
        for entry in data:
            entry_source = _normalize_coverage_source(source or entry.get("source", "gcov_curated"))
            cur.execute(
                """INSERT OR REPLACE INTO coverage (function, block_id, line_start, line_end, hit_count, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (entry["function"], entry["block_id"],
                 entry.get("line_start"), entry.get("line_end"),
                 entry.get("hit_count", 0), entry_source)
            )
            count += 1
        self.conn.commit()
        source_label = ",".join(sources) if sources else "unknown"
        print(f"[sqlite] Imported {count} coverage records ({source_label}).")

    def import_test_results(self, json_path):
        """Import test case results from a JSON file."""
        with open(json_path) as f:
            results = json.load(f)

        cur = self.conn.cursor()
        cur.execute("DELETE FROM test_cases")
        for r in results:
            cur.execute(
                """INSERT OR REPLACE INTO test_cases (name, source, board_l, board_w, cut_l, cut_w,
                   expected_pieces, actual_pieces, passed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["name"], r["source"], r["board_l"], r["board_w"],
                 r["cut_l"], r["cut_w"], r.get("expected_pieces"), r.get("actual"),
                 1 if r.get("passed") else 0)
            )
        self.conn.commit()
        print(f"[sqlite] Imported {len(results)} test results.")

    def import_fuzz_stats(self, json_path):
        """Import fuzzing stats from a JSON file."""
        with open(json_path) as f:
            stats = json.load(f)

        if isinstance(stats, dict):
            stats = [stats]

        cur = self.conn.cursor()
        sources = [entry.get("source", "afl") for entry in stats]
        for source in sources:
            cur.execute("DELETE FROM fuzz_stats WHERE source = ?", (source,))
        for entry in stats:
            cur.execute(
                """INSERT OR REPLACE INTO fuzz_stats
                   (source, total_execs, execs_per_sec, unique_crashes, unique_hangs, paths_total,
                    paths_found, corpus_count, run_time_seconds,
                    afl_replay_count, afl_replay_blocks_added)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.get("source", "afl"),
                    entry.get("total_execs"),
                    entry.get("execs_per_sec"),
                    entry.get("unique_crashes"),
                    entry.get("unique_hangs"),
                    entry.get("paths_total"),
                    entry.get("paths_found"),
                    entry.get("corpus_count"),
                    entry.get("run_time_seconds"),
                    entry.get("afl_replay_count", 0),
                    entry.get("afl_replay_blocks_added", 0),
                )
            )
        self.conn.commit()
        print(f"[sqlite] Imported {len(stats)} fuzz stat records.")

    def get_uncovered_blocks(self):
        """Return basic blocks with zero hit count."""
        cur = self.conn.cursor()
        cur.execute("SELECT function, block_id, line_start, line_end FROM coverage WHERE hit_count = 0")
        return cur.fetchall()

    def get_coverage_summary(self):
        """Return per-function coverage summary."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT function,
                   COUNT(*) as total_blocks,
                   SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END) as covered_blocks,
                   ROUND(100.0 * SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
            FROM coverage
            GROUP BY function
            ORDER BY pct ASC
        """)
        return cur.fetchall()

    def close(self):
        self.conn.close()


# Utilities

_STDLIB_FUNCTIONS = frozenset({
    "printf", "fprintf", "sprintf", "snprintf", "scanf", "fscanf", "sscanf",
    "puts", "putchar", "getchar", "fgets", "fputs",
    "malloc", "calloc", "realloc", "free",
    "memset", "memcpy", "memmove", "memcmp",
    "strlen", "strcpy", "strncpy", "strcat", "strncat", "strcmp", "strncmp",
    "strchr", "strrchr", "strstr", "strcspn", "strspn", "strtok",
    "atoi", "atol", "atof", "strtol", "strtod",
    "abs", "labs", "div", "ldiv",
    "exit", "abort", "atexit",
    "fopen", "fclose", "fread", "fwrite", "fseek", "ftell", "rewind",
})


def _is_user_function(name):
    """Return True if the function is user-defined, not stdlib/compiler builtin."""
    if not name:
        return False
    if name.startswith("llvm.") or name.startswith("__"):
        return False
    if name in _STDLIB_FUNCTIONS:
        return False
    return True


def _demangle(name):
    """Clean up LLVM mangled/internal names. Return None for noise entries."""
    name = name.strip('"').strip()
    if name.startswith("Node0x") or name.startswith("external node"):
        return None
    if name in ("null function", ""):
        return None
    # C++ symbols appear as _Z<len><name><type_suffixes> in the LLVM output.
    m = re.match(r'^_Z(\d+)(\w+)', name)
    if m:
        length = int(m.group(1))
        rest = m.group(2)
        if length <= len(rest):
            name = rest[:length]
        else:
            name = rest
    name = re.sub(r'\.\d+$', '', name)
    if name.startswith("llvm."):
        return None
    return name if name else None


def _extract_instructions(label):
    """Extract instruction text from a CFG basic block label."""
    # Labels look like: {entry:\n  %0 = alloca ...\n  store ...}
    lines = label.replace("\\l", "\n").replace("\\n", "\n").split("\n")
    return "\n".join(l.strip() for l in lines if l.strip())


def _parse_dot_attrs(attr_text):
    attrs = {}
    for match in re.finditer(r'(\w+)=((?:"(?:\\.|[^"])*")|[^,\]]+)', attr_text):
        key = match.group(1)
        value = match.group(2).strip().strip('"')
        attrs[key] = value
    return attrs


def _parse_dot_file(dot_path):
    nodes = {}
    edges = []

    with open(dot_path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(("digraph", "label=", "}")):
                continue

            if "->" in line:
                edge_match = re.match(r'("?[^"\s;]+"?)\s*->\s*("?[^"\s;]+"?)(?:\s*\[(.*)\])?;', line)
                if not edge_match:
                    continue
                src = edge_match.group(1).strip('"').split(":", 1)[0]
                dst = edge_match.group(2).strip('"').split(":", 1)[0]
                attrs = _parse_dot_attrs(edge_match.group(3) or "")
                edges.append(_DotEdge(src, dst, attrs.get("label")))
                continue

            node_match = re.match(r'("?[^"\s;]+"?)\s*\[(.*)\];', line)
            if not node_match:
                continue
            name = node_match.group(1).strip('"')
            attrs = _parse_dot_attrs(node_match.group(2))
            nodes[name] = _DotNode(name, attrs.get("label"))

    return _DotGraph(list(nodes.values()), edges)


# CLI

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import program analysis data into Neo4j + SQLite")
    parser.add_argument("--callgraph", help="Path to callgraph DOT file")
    parser.add_argument("--cfg-dir", help="Directory containing per-function CFG DOT files")
    parser.add_argument("--deps", help="Path to dependency JSON file")
    parser.add_argument("--coverage", help="Path to coverage JSON file")
    parser.add_argument("--coverage-source", help="Override source tag for --coverage rows")
    parser.add_argument("--coverage-baseline", help="Path to curated baseline coverage JSON")
    parser.add_argument("--coverage-replay", help="Path to AFL replay coverage JSON")
    parser.add_argument("--test-results", help="Path to test results JSON file")
    parser.add_argument("--fuzz-stats", help="Path to fuzz stats JSON file")
    parser.add_argument("--clear", action="store_true", help="Clear Neo4j database before import")
    parser.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j import steps")
    parser.add_argument("--skip-sqlite", action="store_true", help="Skip SQLite import steps")
    args = parser.parse_args()

    neo4j_requested = bool(args.clear or args.callgraph or args.cfg_dir or args.deps)
    sqlite_requested = bool(
        args.coverage
        or args.coverage_baseline
        or args.coverage_replay
        or args.test_results
        or args.fuzz_stats
    )

    if args.skip_neo4j:
        print("[neo4j] Skipped by --skip-neo4j.")
    elif neo4j_requested:
        importer = Neo4jImporter()
        try:
            if args.clear:
                importer.clear_database()

            importer.create_indexes()

            if args.callgraph:
                importer.import_callgraph(args.callgraph)
            if args.cfg_dir:
                importer.import_cfg(args.cfg_dir)
            if args.deps:
                importer.import_dependencies(args.deps)
        finally:
            importer.close()

    if args.skip_sqlite:
        print("[sqlite] Skipped by --skip-sqlite.")
    elif sqlite_requested:
        sql = SQLiteManager()
        try:
            if args.coverage:
                sql.import_coverage_json(args.coverage, source=args.coverage_source)
            if args.coverage_baseline:
                sql.import_coverage_json(args.coverage_baseline, source="gcov_curated")
            if args.coverage_replay:
                sql.import_coverage_json(args.coverage_replay, source="gcov_afl_replay")
            if args.test_results:
                sql.import_test_results(args.test_results)
            if args.fuzz_stats:
                sql.import_fuzz_stats(args.fuzz_stats)
        finally:
            sql.close()

    print("[done] Import complete.")
