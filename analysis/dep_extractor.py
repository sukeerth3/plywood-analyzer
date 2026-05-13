"""Extracts source-level dependency edges from LLVM IR files."""

import re
import json
import argparse
from collections import defaultdict

try:
    from analysis.graph_importer import _demangle, _is_user_function
except ModuleNotFoundError:
    from graph_importer import _demangle, _is_user_function


class DebugInfoMap:
    """Parses LLVM debug metadata to map SSA registers to source-level names."""

    def __init__(self, lines):
        self.metadata = {}       # !NNN -> parsed dict
        self.reg_to_name = {}    # (func, "%reg") -> "source_name"
        self.struct_fields = {}  # ("StructName", field_index) -> "field_name"
        self.reg_to_type = {}    # (func, "%reg") -> "%struct.TypeName"
        self._parse_metadata(lines)
        self._parse_dbg_declares(lines)
        self._parse_struct_types(lines)

    def _parse_metadata(self, lines):
        """Parse all metadata definitions from the IR."""
        for line in lines:
            m = re.match(r'^(!\d+)\s*=\s*!?(.+)$', line.strip())
            if not m:
                continue
            mid = m.group(1)
            body = m.group(2)

            # DILocalVariable
            lv = re.search(r'DILocalVariable\(name:\s*"([^"]+)"', body)
            if lv:
                self.metadata[mid] = {"kind": "local_var", "name": lv.group(1)}
                continue

            # DICompositeType with elements list
            ct = re.search(
                r'DICompositeType\(.*?name:\s*"([^"]+)".*?elements:\s*(!\d+)', body
            )
            if ct:
                self.metadata[mid] = {
                    "kind": "composite_type",
                    "name": ct.group(1),
                    "elements_ref": ct.group(2),
                }
                continue

            # DIDerivedType member
            dt = re.search(
                r'DIDerivedType\(tag:\s*DW_TAG_member,\s*name:\s*"([^"]+)"', body
            )
            if dt:
                self.metadata[mid] = {"kind": "member", "name": dt.group(1)}
                continue

            # Element list: !NNN = !{!A, !B, ...}
            el = re.match(r'\{((?:!\d+(?:,\s*)?)*)\}', body)
            if el:
                refs = re.findall(r'(!\d+)', el.group(1))
                self.metadata[mid] = {"kind": "list", "refs": refs}

    def _parse_dbg_declares(self, lines):
        """Extract register-to-source-name mappings from llvm.dbg.declare calls."""
        current_func = None
        for line in lines:
            stripped = line.strip()

            func_match = re.match(r'define\s+.*@(\w+)\s*\(', stripped)
            if func_match:
                current_func = func_match.group(1)
                continue
            if stripped == "}" and current_func:
                current_func = None
                continue
            if not current_func:
                continue

            # call void @llvm.dbg.declare(metadata <type>* %reg, metadata !NNN, ...)
            dbg = re.search(
                r'@llvm\.dbg\.declare\(metadata\s+\S+\s+(%[\w.]+),\s*metadata\s+(!\d+)',
                stripped,
            )
            if not dbg:
                continue
            reg = dbg.group(1)
            mid = dbg.group(2)
            meta = self.metadata.get(mid)
            if meta and meta["kind"] == "local_var":
                self.reg_to_name[(current_func, reg)] = meta["name"]

    def _parse_struct_types(self, lines):
        """Build struct field maps from metadata and IR struct definitions."""
        # From debug info: walk composite types -> element lists -> member names
        for mid, meta in list(self.metadata.items()):
            if meta.get("kind") != "composite_type":
                continue
            struct_name = meta["name"]
            elems_ref = meta.get("elements_ref")
            elems = self.metadata.get(elems_ref)
            if not elems or elems["kind"] != "list":
                continue
            for idx, ref in enumerate(elems["refs"]):
                member = self.metadata.get(ref)
                if member and member["kind"] == "member":
                    self.struct_fields[(struct_name, idx)] = member["name"]

        # Also parse IR-level struct type definitions to map %struct.X field order
        # %struct.Dimensions = type { i32, i32 }
        # This gives us the IR-level struct name -> fields correspondence
        # (we already have it via debug info, but this confirms the index mapping)

    def resolve_name(self, func, reg):
        """Resolve a register to a source-level name, or return cleaned register name."""
        name = self.reg_to_name.get((func, reg))
        if name:
            return name
        return _clean_var(reg)

    def resolve_gep_field(self, struct_ir_type, field_idx):
        """Resolve a GEP struct field access to a source-level field name."""
        # struct_ir_type like "%struct.Dimensions" -> "Dimensions"
        struct_name = struct_ir_type.replace("%struct.", "")
        return self.struct_fields.get((struct_name, field_idx))


def parse_llvm_ir(ir_path):
    """Parse an LLVM IR file and extract variable dependencies per function."""
    with open(ir_path) as f:
        lines = f.readlines()

    debug_info = DebugInfoMap(lines)
    dependencies = []
    current_func = None
    var_sources = {}      # var_name -> set of source var names
    # Track which register holds which named pointer (for load/store through alloca)
    ptr_names = {}        # %ptr_reg -> source_name  (from dbg.declare)
    # Track GEP results: %gep_reg -> "varname.fieldname"
    gep_names = {}

    for line in lines:
        line = line.strip()

        # Function definition
        func_match = re.match(r'define\s+.*@(\w+)\s*\(', line)
        if func_match:
            if current_func:
                dependencies.extend(
                    _build_deps(current_func, var_sources, debug_info)
                )
            current_func = func_match.group(1)
            var_sources = defaultdict(set)
            ptr_names = {}
            gep_names = {}
            # Pre-populate ptr_names from debug info
            for (fn, reg), name in debug_info.reg_to_name.items():
                if fn == current_func:
                    ptr_names[reg] = name
            continue

        # End of function
        if line == "}" and current_func:
            dependencies.extend(
                _build_deps(current_func, var_sources, debug_info)
            )
            current_func = None
            var_sources = defaultdict(set)
            ptr_names = {}
            gep_names = {}
            continue

        if not current_func:
            continue

        # Skip debug intrinsics — they don't represent data flow
        if "@llvm.dbg." in line:
            continue

        # GEP: %x = getelementptr inbounds %struct.Dimensions, %struct.Dimensions* %ptr, i32 0, i32 <idx>
        gep_match = re.match(
            r'(%[\w.]+)\s*=\s*getelementptr\s+inbounds\s+(%struct\.\w+),\s*'
            r'\S+\s+(%[\w.]+),\s*i32\s+0,\s*i32\s+(\d+)',
            line,
        )
        if gep_match:
            dest = gep_match.group(1)
            struct_type = gep_match.group(2)
            base_reg = gep_match.group(3)
            field_idx = int(gep_match.group(4))

            base_name = ptr_names.get(base_reg, _clean_var(base_reg))
            field_name = debug_info.resolve_gep_field(struct_type, field_idx)

            if field_name:
                resolved = f"{base_name}.{field_name}"
            else:
                resolved = f"{base_name}.field{field_idx}"

            gep_names[dest] = resolved
            ptr_names[dest] = resolved

            var_sources[resolved].add(base_name)
            continue

        # Load: %x = load <type>, <type>* %ptr
        load_match = re.match(r'(%[\w.]+)\s*=\s*load\s+.*,\s*\S+\s+(%[\w.]+)', line)
        if load_match:
            dest = load_match.group(1)
            ptr = load_match.group(2)

            src_name = gep_names.get(ptr) or ptr_names.get(ptr) or _clean_var(ptr)
            dest_resolved = _clean_var(dest)
            # Propagate the name: if we load from a named pointer, the result carries that name
            ptr_names[dest] = src_name

            var_sources[dest_resolved].add(src_name)
            continue

        # Store: store <type> %val, <type>* %ptr
        store_match = re.match(r'store\s+\S+\s+(%[\w.]+),\s*\S+\s+(%[\w.]+)', line)
        if store_match:
            val = store_match.group(1)
            ptr = store_match.group(2)

            val_name = ptr_names.get(val, _clean_var(val))
            ptr_name = gep_names.get(ptr) or ptr_names.get(ptr) or _clean_var(ptr)

            var_sources[ptr_name].add(val_name)
            continue

        # General assignment: %result = <op> <type> %operand1, %operand2
        assign_match = re.match(r'(%[\w.]+)\s*=\s*(\w+)\s+.*', line)
        if assign_match:
            dest = assign_match.group(1)
            op = assign_match.group(2)

            # Skip non-data-flow ops
            if op in ("alloca", "bitcast", "getelementptr"):
                # bitcast and plain getelementptr (non-struct) just pass through
                rhs_refs = re.findall(r'(%[\w.]+)', line[line.index("=") + 1 :])
                for ref in rhs_refs:
                    if ref != dest and ref in ptr_names:
                        ptr_names[dest] = ptr_names[ref]
                        break
                continue

            # Find all %var references on the right side
            rhs = line[line.index("=") + 1 :]
            sources = re.findall(r'(%[\w.]+)', rhs)

            dest_name = _clean_var(dest)
            for src in sources:
                if src != dest:
                    src_name = ptr_names.get(src, _clean_var(src))
                    var_sources[dest_name].add(src_name)
            continue

    dependencies.extend(_extract_cross_call_deps(lines, debug_info))

    return dependencies


class FunctionIR:
    """Small index of one function body for cross-call dependency extraction."""

    def __init__(self, name, header, lines):
        self.name = name
        self.header = header
        self.lines = lines
        self.formals = _parse_formals(header, name)
        self.defs = _build_value_defs(lines)
        self.copies = _build_memory_copies(self)


def _extract_cross_call_deps(lines, debug_info):
    """Build source-level data-flow bridges across user-function call args."""
    functions = _collect_functions(lines)
    deps = []
    calls_by_caller = defaultdict(list)

    for caller in functions.values():
        caller_clean = _demangle(caller.name) or caller.name
        if not _is_user_function(caller_clean):
            continue

        for call in _iter_user_calls(caller, functions):
            callee = functions[call["callee"]]
            pairs = []

            for actual, formal in _paired_actuals_and_formals(call["actuals"], callee.formals):
                if formal["is_sret"]:
                    continue

                caller_name = _resolve_actual_name(
                    caller, actual["value"], call["line_idx"], debug_info
                )
                callee_name = _resolve_formal_name(callee, formal["value"], debug_info)
                if not caller_name or not callee_name:
                    continue

                deps.append({
                    "from": caller_name,
                    "to": callee_name,
                    "function": caller.name,
                    "type": "cross_call",
                    "callee": callee.name,
                })
                pairs.append({
                    "caller_name": caller_name,
                    "callee_name": callee_name,
                    "actual_byref": _is_byref_pointer_arg(actual["raw"], formal["raw"]),
                    "source_function": callee.name,
                })

            if pairs:
                call["pairs"] = pairs
                calls_by_caller[caller.name].append(call)

    deps.extend(_build_byref_sequence_edges(calls_by_caller))
    return deps


def _collect_functions(lines):
    functions = {}
    current_name = None
    current_header = None
    current_lines = []

    for raw in lines:
        stripped = raw.strip()
        func_match = re.match(r'define\s+.*@([^\s(]+)\s*\(', stripped)
        if func_match:
            current_name = func_match.group(1)
            current_header = stripped
            current_lines = []
            continue

        if stripped == "}" and current_name:
            functions[current_name] = FunctionIR(current_name, current_header, current_lines)
            current_name = None
            current_header = None
            current_lines = []
            continue

        if current_name:
            current_lines.append(stripped)

    return functions


def _iter_user_calls(func_ir, functions):
    for idx, line in enumerate(func_ir.lines):
        if "@llvm.dbg." in line:
            continue
        call_match = re.search(r'\bcall\b.*@([^\s(]+)\s*\(', line)
        if not call_match:
            continue
        callee = call_match.group(1)
        clean = _demangle(callee) or callee
        if not _is_user_function(clean) or callee not in functions:
            continue
        yield {
            "line_idx": idx,
            "line": line,
            "callee": callee,
            "actuals": _parse_call_actuals(line, callee),
        }


def _parse_formals(header, func_name):
    arg_text = _extract_arg_text(header, f"@{func_name}")
    if arg_text is None or not arg_text.strip():
        return []

    formals = []
    for raw in _split_llvm_args(arg_text):
        value = _last_value_token(raw)
        if not value or not value.startswith("%"):
            continue
        formals.append({
            "raw": raw,
            "value": value,
            "is_sret": "sret" in raw,
        })
    return formals


def _parse_call_actuals(line, callee):
    arg_text = _extract_arg_text(line, f"@{callee}")
    if arg_text is None:
        return []
    actuals = []
    for raw in _split_llvm_args(arg_text):
        actuals.append({
            "raw": raw,
            "value": _last_value_token(raw),
        })
    return actuals


def _extract_arg_text(text, symbol):
    start = text.find(symbol)
    if start == -1:
        return None
    open_idx = text.find("(", start + len(symbol))
    if open_idx == -1:
        return None

    depth = 0
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:idx]
    return None


def _split_llvm_args(arg_text):
    args = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_string = False
    escaped = False

    for idx, ch in enumerate(arg_text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
        elif ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            part = arg_text[start:idx].strip()
            if part:
                args.append(part)
            start = idx + 1

    tail = arg_text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _last_value_token(text):
    tokens = re.findall(r'[%@][\w.$]+', text)
    tokens = [tok for tok in tokens if not tok.startswith("%struct.")]
    return tokens[-1] if tokens else None


def _paired_actuals_and_formals(actuals, formals):
    for actual, formal in zip(actuals, formals):
        if not actual.get("value") or not formal.get("value"):
            continue
        yield actual, formal


def _build_value_defs(lines):
    defs = {}
    for idx, line in enumerate(lines):
        m = re.match(r'(%[\w.]+)\s*=\s*(.+)$', line)
        if m:
            defs[m.group(1)] = (idx, line)
    return defs


def _build_memory_copies(func_ir):
    copies = defaultdict(list)
    for idx, line in enumerate(func_ir.lines):
        if "@llvm.memcpy" not in line:
            continue
        call_match = re.search(r'@(llvm\.memcpy[^\s(]*)\s*\(', line)
        if not call_match:
            continue
        actuals = _parse_call_actuals(line, call_match.group(1))
        if len(actuals) < 2:
            continue
        dest = _trace_pointer_base(func_ir, actuals[0]["value"], idx)
        src = _trace_pointer_base(func_ir, actuals[1]["value"], idx)
        if dest and src and dest != src:
            copies[dest].append((idx, src))
    return copies


def _trace_pointer_base(func_ir, value, before_idx, seen=None):
    if not value or not value.startswith("%"):
        return value
    seen = seen or set()
    if value in seen:
        return None
    seen.add(value)

    defn = func_ir.defs.get(value)
    if not defn:
        return value
    def_idx, line = defn
    if def_idx >= before_idx:
        return value

    if re.search(r'=\s*(bitcast|addrspacecast)\b', line):
        refs = _ssa_refs_after_equals(line)
        return _trace_pointer_base(func_ir, refs[0], def_idx, seen) if refs else value

    gep = _parse_gep(line)
    if gep:
        return _trace_pointer_base(func_ir, gep["base"], def_idx, seen)

    return value


def _resolve_actual_name(func_ir, value, before_idx, debug_info):
    return _resolve_value_name(func_ir, value, before_idx, debug_info)


def _resolve_formal_name(func_ir, formal, debug_info):
    direct = debug_info.reg_to_name.get((func_ir.name, formal))
    if direct:
        return direct

    for idx, line in enumerate(func_ir.lines):
        store = _parse_store(line)
        if not store or store["value"] != formal:
            continue
        name = _resolve_value_name(func_ir, store["ptr"], idx, debug_info)
        if name:
            return name
    return None


def _resolve_value_name(func_ir, value, before_idx, debug_info, seen=None):
    if not value:
        return None
    if value.startswith("@"):
        return value.lstrip("@")
    if not value.startswith("%"):
        return None

    seen = seen or set()
    if value in seen:
        return None
    seen.add(value)

    direct = debug_info.reg_to_name.get((func_ir.name, value))
    if direct:
        return direct

    copied_from = _latest_copy_source(func_ir, value, before_idx)
    if copied_from:
        copied_name = _resolve_value_name(func_ir, copied_from, before_idx, debug_info, seen)
        if copied_name:
            return copied_name

    defn = func_ir.defs.get(value)
    if not defn:
        return None
    def_idx, line = defn
    if def_idx >= before_idx:
        return None

    load = _parse_load(line)
    if load:
        return _resolve_value_name(func_ir, load["ptr"], def_idx, debug_info, seen)

    if re.search(r'=\s*(bitcast|addrspacecast)\b', line):
        refs = _ssa_refs_after_equals(line)
        if refs:
            return _resolve_value_name(func_ir, refs[0], def_idx, debug_info, seen)

    gep = _parse_gep(line)
    if gep:
        base_name = _resolve_value_name(func_ir, gep["base"], def_idx, debug_info, seen)
        if not base_name:
            return None
        field_name = debug_info.resolve_gep_field(gep["struct_type"], gep["field_idx"])
        return f"{base_name}.{field_name}" if field_name else base_name

    return None


def _latest_copy_source(func_ir, value, before_idx):
    candidates = [
        (idx, src)
        for idx, src in func_ir.copies.get(value, [])
        if idx < before_idx
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _parse_load(line):
    m = re.match(r'(%[\w.]+)\s*=\s*load\s+.*,\s*\S+\s+(%[\w.]+)', line)
    if not m:
        return None
    return {"dest": m.group(1), "ptr": m.group(2)}


def _parse_store(line):
    m = re.match(r'store\s+.+?\s+([%@][\w.$]+),\s*.+?\s+([%@][\w.$]+)', line)
    if not m:
        return None
    return {"value": m.group(1), "ptr": m.group(2)}


def _parse_gep(line):
    m = re.match(
        r'(%[\w.]+)\s*=\s*getelementptr\s+inbounds\s+(%struct\.\w+),\s*'
        r'.*?\s+(%[\w.]+),\s*i\d+\s+0,\s*i\d+\s+(\d+)',
        line,
    )
    if not m:
        return None
    return {
        "dest": m.group(1),
        "struct_type": m.group(2),
        "base": m.group(3),
        "field_idx": int(m.group(4)),
    }


def _ssa_refs_after_equals(line):
    rhs = line[line.index("=") + 1:] if "=" in line else line
    return [
        ref for ref in re.findall(r'%[\w.]+', rhs)
        if not ref.startswith("%struct.")
    ]


def _is_byref_pointer_arg(actual_raw, formal_raw):
    if "sret" in actual_raw or "sret" in formal_raw:
        return False
    if "byval" in actual_raw or "byval" in formal_raw:
        return False
    return "*" in actual_raw and "*" in formal_raw


def _build_byref_sequence_edges(calls_by_caller):
    deps = []
    for calls in calls_by_caller.values():
        for idx, source_call in enumerate(calls):
            source_pairs = [p for p in source_call.get("pairs", []) if p["actual_byref"]]
            if not source_pairs:
                continue

            for sink_call in calls[idx + 1:]:
                for source_pair in source_pairs:
                    for sink_pair in sink_call.get("pairs", []):
                        if source_pair["caller_name"] != sink_pair["caller_name"]:
                            continue
                        deps.append({
                            "from": source_pair["callee_name"],
                            "to": sink_pair["callee_name"],
                            "function": source_pair["source_function"],
                            "type": "cross_call",
                            "callee": sink_call["callee"],
                        })
    return deps


def _build_deps(func_name, var_sources, debug_info):
    """Convert var_sources dict into flat dependency list with source-level names."""
    deps = []
    seen = set()
    for dest, sources in var_sources.items():
        dest_name = _resolve_dep_name(dest, func_name, debug_info)
        if not dest_name or _is_numeric_name(dest_name):
            continue
        for src in sources:
            for src_name in _expand_source_names(src, var_sources, func_name, debug_info):
                if not src_name or _is_numeric_name(src_name):
                    continue

                # Skip self-dependencies and trivial register-to-register noise
                if src_name == dest_name:
                    continue
                key = (src_name, dest_name, func_name)
                if key in seen:
                    continue
                seen.add(key)

                deps.append({
                    "from": src_name,
                    "to": dest_name,
                    "function": func_name,
                    "type": "data_flow",
                })
    return deps


def _clean_var(name):
    """Clean LLVM variable name for display."""
    cleaned = name.lstrip("%").replace(".", "_")
    if cleaned.isdigit():
        return name
    return cleaned


def _is_numeric_name(name):
    """Return true for anonymous numeric SSA register labels."""
    return str(name).lstrip("%").isdigit()


def _resolve_dep_name(name, func_name, debug_info):
    if name is None:
        return None
    return debug_info.resolve_name(func_name, name) if str(name).startswith("%") else name


def _expand_source_names(name, var_sources, func_name, debug_info, seen=None):
    """Expand anonymous SSA intermediates into their source-level inputs."""
    resolved = _resolve_dep_name(name, func_name, debug_info)
    if not resolved:
        return set()
    if not _is_numeric_name(resolved):
        return {resolved}

    seen = seen or set()
    if resolved in seen:
        return set()
    seen.add(resolved)

    expanded = set()
    for upstream in var_sources.get(resolved, set()):
        expanded.update(_expand_source_names(upstream, var_sources, func_name, debug_info, seen))
    return expanded


def deduplicate(deps):
    """Remove duplicate dependency edges."""
    seen = set()
    unique = []
    for d in deps:
        key = (d["from"], d["to"], d["function"], d.get("callee"))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract data dependencies from LLVM IR")
    parser.add_argument("ir_file", help="Path to .ll file")
    parser.add_argument("-o", "--output", default="data/dependencies.json",
                        help="Output JSON path")
    args = parser.parse_args()

    deps = parse_llvm_ir(args.ir_file)
    deps = deduplicate(deps)

    with open(args.output, "w") as f:
        json.dump(deps, f, indent=2)

    print(f"Extracted {len(deps)} dependency edges -> {args.output}")
