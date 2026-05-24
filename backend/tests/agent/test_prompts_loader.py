"""问股期 1 — Task 27:turtle prompts loader 测试。"""

from pathlib import Path

from services.agent.prompts import loader

PROMPTS_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "agent" / "prompts" / "turtle"
)


def test_six_prompt_files_exist():
    expected = [
        "coordinator.md",
        "phase3_quantitative.md",
        "phase3_valuation.md",
        "references/shared_tables.md",
        "references/judgment_examples_turtle.md",
        "references/factor_interface.md",
    ]
    for rel in expected:
        path = PROMPTS_DIR / rel
        assert path.exists(), f"missing {rel}"
        assert path.stat().st_size > 500, f"{rel} suspiciously small"


def test_load_phase3_quant_renders_output_dir():
    text = loader.load("phase3_quantitative.md", output_dir="/tmp/run_xyz")
    assert "{output_dir}" not in text
    assert "/tmp/run_xyz" in text


def test_load_references_relative_path():
    text = loader.load(
        "phase3_quantitative.md",
        output_dir="/tmp/x",
        expand_includes=True,
    )
    assert "穿透回报率" in text
