from pathlib import Path

from analysis.dep_extractor import deduplicate, parse_llvm_ir


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IR_PATH = PROJECT_ROOT / "build" / "plywood_calc.ll"


def test_cross_call_edges_from_real_ir():
    assert IR_PATH.exists(), f"missing test IR: {IR_PATH}"

    deps = deduplicate(parse_llvm_ir(str(IR_PATH)))
    cross_edges = {
        (
            dep.get("from"),
            dep.get("to"),
            dep.get("function"),
            dep.get("callee"),
            dep.get("type"),
        )
        for dep in deps
        if dep.get("type") == "cross_call"
    }

    expected = {
        (
            "board",
            "board",
            "_Z9get_inputP10DimensionsS0_",
            "_Z14calculate_cuts10DimensionsS_",
            "cross_call",
        ),
        (
            "cut",
            "cut",
            "_Z9get_inputP10DimensionsS0_",
            "_Z14calculate_cuts10DimensionsS_",
            "cross_call",
        ),
        (
            "board",
            "board",
            "main",
            "_Z20render_visualization9CutResult10DimensionsS0_",
            "cross_call",
        ),
        (
            "cut",
            "cut",
            "main",
            "_Z20render_visualization9CutResult10DimensionsS0_",
            "cross_call",
        ),
    }

    assert expected <= cross_edges
