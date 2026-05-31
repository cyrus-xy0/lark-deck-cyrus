#!/usr/bin/env python3
"""Run Cyrus skill-level happy/corner contract cases.

The companion JSON file is the human-readable test matrix. This runner keeps
the executable checks offline and deterministic: it validates schema handoffs,
CLI gates, dry-run ingestion, and the confirmed pipeline smoke test.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[1]
CASES_JSON = REPO / "evals" / "cyrus-skill-contract-cases.json"
RUNS_ROOT = REPO / "runs" / "skill-contract-cases"
RUNS_DIR = REPO / "runs"

GENERATOR = REPO / "server" / "generator.py"
GENERATOR_REQUEST = REPO / "server" / "examples" / "brief-request.json"
PARSER = REPO / "skills" / "upload-parser" / "parse.py"
OUTLINE_VALIDATOR = REPO / "skills" / "deck-planner" / "validate-outline.py"
COMPILE_OUTLINE = REPO / "skills" / "deck-renderer" / "deck-json" / "compile-outline.py"
VALIDATE_DECK = REPO / "skills" / "deck-renderer" / "deck-json" / "validate-deck.py"
RENDER_DECK = REPO / "skills" / "deck-renderer" / "deck-json" / "render-deck.py"
AUDITOR = REPO / "skills" / "deck-auditor" / "audit.py"
SIMULATOR = REPO / "skills" / "pitch-simulator" / "simulate-pitch.py"
VALIDATE_REHEARSAL = REPO / "skills" / "pitch-simulator" / "validate-rehearsal.py"
INGESTOR = REPO / "skills" / "deck-ingestor" / "ingest.py"
PIPELINE_CONTRACT = REPO / "evals" / "run-cyrus-pipeline-contract.py"
PIPELINE = REPO / "scripts" / "run_cyrus_pipeline.py"

CONTRACT_VALIDATOR = REPO / "skills" / "lark-deck-cyrus" / "schema" / "validate-contract.py"
SOURCE_DOSSIER_SCHEMA = REPO / "skills" / "lark-deck-cyrus" / "schema" / "source-dossier.schema.json"
AUDIT_SCHEMA = REPO / "skills" / "lark-deck-cyrus" / "schema" / "audit-report.schema.json"
INGESTION_SCHEMA = REPO / "skills" / "lark-deck-cyrus" / "schema" / "ingestion-manifest.schema.json"
SAMPLE_HTML = REPO / "skills" / "deck-renderer" / "examples" / "sample-deck.html"


class CaseFailure(AssertionError):
    pass


class Context:
    def __init__(self, root: Path):
        self.root = root
        self.paths: dict[str, Path] = {}
        self.data: dict[str, Any] = {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    os.environ.setdefault("CYRUS_MAGIC_DRY_RUN", "1")
    os.environ.setdefault("CYRUS_PUBLISH_TARGET", "magic-page")
    os.environ.setdefault("GENERATOR_VISUAL_AUDIT", "0")
    try:
        return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            cmd,
            124,
            exc.stdout if isinstance(exc.stdout, str) else "",
            exc.stderr if isinstance(exc.stderr, str) else f"timeout after {timeout}s",
        )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def require_proc_ok(proc: subprocess.CompletedProcess[str], label: str) -> None:
    require(proc.returncode == 0, f"{label} failed rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


def require_proc_fail(proc: subprocess.CompletedProcess[str], label: str) -> None:
    require(proc.returncode != 0, f"{label} unexpectedly passed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


def validate_contract(schema: Path, instance: Path) -> None:
    proc = run([sys.executable, str(CONTRACT_VALIDATOR), "--schema", str(schema), "--instance", str(instance)])
    require_proc_ok(proc, f"contract validation {instance.name}")


def load_task_json(task_id: str) -> dict[str, Any]:
    return read_json(RUNS_DIR / task_id / "task.json")


def create_generator_plan_task(ctx: Context, key: str) -> dict[str, Any]:
    task_id = ctx.data.get(key)
    if task_id:
        return load_task_json(str(task_id))
    proc = run([
        sys.executable,
        str(GENERATOR),
        "create",
        "--request",
        str(GENERATOR_REQUEST),
        "--plan-only",
    ], timeout=45)
    require_proc_ok(proc, f"generator create plan-only {key}")
    task = json.loads(proc.stdout)
    ctx.data[key] = task["id"]
    return task


def create_generator_rehearsal_task(ctx: Context, key: str) -> dict[str, Any]:
    task_id = ctx.data.get(key)
    if task_id:
        return load_task_json(str(task_id))
    plan_task = create_generator_plan_task(ctx, f"{key}-plan")
    proc = run([sys.executable, str(GENERATOR), "confirm-outline", plan_task["id"]], timeout=60)
    require_proc_ok(proc, f"generator confirm-outline {key}")
    task = json.loads(proc.stdout)
    require(task["status"] == "awaiting_rehearsal_decision", "confirmed task did not pause at rehearsal decision")
    require(task.get("confirmation_required") == "rehearsal", "confirmed task did not require rehearsal confirmation")
    require(not task.get("artifacts", {}).get("magic_page_url"), "deck was published before rehearsal acceptance")
    ctx.data[key] = task["id"]
    return task


def create_generator_accepted_task(ctx: Context, key: str) -> dict[str, Any]:
    task_id = ctx.data.get(key)
    if task_id:
        return load_task_json(str(task_id))
    rehearsal_task = create_generator_rehearsal_task(ctx, f"{key}-rehearsal")
    proc = run([sys.executable, str(GENERATOR), "accept-rehearsal", rehearsal_task["id"]], timeout=45)
    require_proc_ok(proc, f"generator accept-rehearsal {key}")
    task = json.loads(proc.stdout)
    require(task["status"] == "awaiting_deck_confirmation", "accepted task did not pause for ingestion confirmation")
    require(task.get("confirmation_required") == "ingestion", "accepted task did not require ingestion confirmation")
    ctx.data[key] = task["id"]
    return task


def design_spec(role: str, memory: str) -> dict[str, Any]:
    return {
        "q0_role": role,
        "q1_memory": memory,
        "q2_hierarchy": {
            "a": memory,
            "b": "三段式证据或动作",
            "c": "页脚来源和限制",
            "d": "待确认事实不放大展示",
        },
        "q3_mood": "克制、业务现场感、偏决策沟通",
        "q4_tradeoff": "避免把示意讲成已验证客户事实",
        "six_dimensions": [
            "密度: 只保留一个主张和三组支撑",
            "层级: A 档是判断句, B 档是动作或证据",
            "证据锚点: 标注用户提供或待确认",
            "视觉节奏: 与前后页形成疏密变化",
            "语言风格: 少形容词, 多业务动作",
            "会议用途: 推动下一步试点确认",
        ],
    }


def slide(
    *,
    key: str,
    title: str,
    role: str,
    layout: str,
    variant: str | None = None,
    hero: bool = False,
) -> dict[str, Any]:
    candidate = {"layout": layout, "rationale": "contract fixture"}
    if variant:
        candidate["variant"] = variant
    return {
        "key": key,
        "title": title,
        "role": role,
        "message": f"{title}。",
        "key_idea": f"{title}是本页唯一要记住的判断。",
        "emphasis": "把判断落到可执行动作,不扩写未确认结果。",
        "talk_track": "先讲业务时刻,再讲动作闭环,最后指出需要确认的证据。",
        "proof_needed": ["用户提供的当前流程样例"],
        "asset_need": [],
        "hero": hero,
        "density_budget": "1 个主判断, 3 个支撑点, 不超过 90 字正文。",
        "design_spec": design_spec(role, f"{title}。"),
        "content_completion": "从 brief 安全改写,不新增客户数据或 ROI 数字。",
        "fact_boundary": "只能说这是试点建议和待确认假设,不能说客户已验证效果。",
        "content_beats": ["现状", "动作", "下一步"],
        "layout_candidate": candidate,
        "visual_intent": "沿用 H5 母版,保持单一视觉中心。",
        "assets": [],
        "evidence": ["待用户补充流程样例"],
        "risk_flags": ["证据未确认"],
        "risk": ["不编造效果数字"],
    }


def rich_outline() -> dict[str, Any]:
    return {
        "version": "1.0",
        "brief": {
            "title": "门店 SOP agent 试点方案",
            "audience": "连锁门店 COO 和运营负责人",
            "requester_context": "Cyrus skill contract eval",
            "objective": "确认一个两周试点范围",
            "success_metric": "确认试点场景、素材清单和负责人",
            "delivery_mode": "local-agent",
            "constraints": ["默认中文", "不编造客户数据"],
        },
        "scene": {
            "industry": "消费零售",
            "segment": "连锁门店",
            "user_role": "运营负责人",
            "business_moment": "SOP 发布、执行和复盘",
            "core_tension": "总部要求清楚,门店动作和反馈不能稳定闭环",
            "confidence": "medium",
        },
        "thesis": {
            "one_sentence": "把 SOP 从文档通知升级成 bot 入口和 agent 闭环。",
            "pain_points": [
                {
                    "name": "动作不可追踪",
                    "why_now": "活动节奏变快,区域经理无法逐店盯执行。",
                    "impact": "复盘只能看结果,难以定位动作差异。",
                    "evidence_level": "hypothesis",
                    "evidence_needed": "客户提供一次 SOP 或巡检记录。",
                }
            ],
            "solution_angle": "用飞书 bot 承接一线入口,用 agent 串起知识、任务、异常和复盘。",
            "differentiation": "先做小闭环试点,再决定规模化。",
        },
        "knowledge_refs": [
            {
                "source": "local-cache",
                "query": "消费零售 门店 SOP agent",
                "title": "本地行业知识包",
                "used_for": "构造测试大纲的业务语境",
            }
        ],
        "outline": {
            "arc": "先定义门店 SOP 的执行断点,再展示 bot + agent 的动作闭环,最后收束到两周试点清单。",
            "slides": [
                slide(key="cover", title="门店 SOP agent 试点方案", role="cover", layout="cover", hero=True),
                slide(key="agent-loop", title="SOP 要从通知变成动作闭环", role="solution", layout="content", variant="3up"),
                slide(key="next-step", title="下一步确认试点场景和素材清单", role="closing", layout="end"),
            ],
        },
        "asset_plan": [],
        "open_questions": ["是否有一份真实 SOP 或巡检样例可以引用?"],
        "claim_discipline": {
            "unsupported_claims": ["不能写提升百分比或已验证 ROI。"],
            "needs_user_confirmation": ["试点门店范围和负责人。"],
        },
        "handoff": {
            "target_skill": "deck-renderer",
            "deckjson_strategy": "direct",
            "notes": "contract eval fixture; real production still waits for user confirmation.",
        },
    }


def ensure_outline(ctx: Context) -> Path:
    path = ctx.paths.get("outline")
    if path and path.exists():
        return path
    path = ctx.root / "fixtures" / "rich-outline.json"
    write_json(path, rich_outline())
    ctx.paths["outline"] = path
    return path


def ensure_rendered(ctx: Context) -> tuple[Path, Path, Path]:
    deck_path = ctx.paths.get("deck")
    html_path = ctx.paths.get("html")
    output_dir = ctx.paths.get("render_output")
    if deck_path and html_path and output_dir and deck_path.exists() and html_path.exists():
        return deck_path, html_path, output_dir

    outline = ensure_outline(ctx)
    output_dir = ctx.root / "renderer-happy" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    deck_path = output_dir / "deck.json"
    compile_report = output_dir / "compile-report.json"
    feedback = output_dir / "FEEDBACK.md"

    proc = run([
        sys.executable,
        str(COMPILE_OUTLINE),
        str(outline),
        str(deck_path),
        "--report",
        str(compile_report),
        "--feedback",
        str(feedback),
    ])
    require_proc_ok(proc, "compile-outline")

    proc = run([sys.executable, str(VALIDATE_DECK), str(deck_path)])
    require_proc_ok(proc, "validate-deck happy")

    proc = run([
        sys.executable,
        str(RENDER_DECK),
        str(deck_path),
        str(output_dir),
        "--offline-cache",
        "--shared",
        "copy",
        "--skip-fit-check",
    ])
    require_proc_ok(proc, "render-deck")

    html_path = output_dir / "index.html"
    require(html_path.exists(), "render output missing index.html")
    require((output_dir / "texts.md").exists(), "render output missing texts.md")
    require(feedback.exists(), "compile output missing FEEDBACK.md")

    ctx.paths.update({"deck": deck_path, "html": html_path, "render_output": output_dir})
    return deck_path, html_path, output_dir


def ensure_audit(ctx: Context) -> Path:
    audit_json = ctx.paths.get("audit_json")
    if audit_json and audit_json.exists():
        return audit_json
    deck_path, html_path, _ = ensure_rendered(ctx)
    out = ctx.root / "auditor-happy"
    out.mkdir(parents=True, exist_ok=True)
    audit_json = out / "audit-report.json"
    proc = run([
        sys.executable,
        str(AUDITOR),
        str(html_path),
        "--deck-json",
        str(deck_path),
        "--report",
        str(out / "AUDIT_REPORT.md"),
        "--json-report",
        str(audit_json),
        "--h5-report",
        str(out / "H5_CHECKONLY_REPORT.md"),
        "--no-visual",
        "--no-strict",
    ])
    require_proc_ok(proc, "deck-auditor happy")
    validate_contract(AUDIT_SCHEMA, audit_json)
    payload = read_json(audit_json)
    require(payload.get("verdict") == "pass", "auditor happy verdict was not pass")
    ctx.paths["audit_json"] = audit_json
    return audit_json


def case_parser_html_happy(_case: dict[str, Any], ctx: Context) -> None:
    out = ctx.root / "parser-html-happy"
    proc = run([sys.executable, str(PARSER), str(SAMPLE_HTML), "--brief", "基于旧 HTML deck 生成新提案", "--output-dir", str(out)])
    require_proc_ok(proc, "upload-parser html")
    dossier = out / "source-dossier.json"
    validate_contract(SOURCE_DOSSIER_SCHEMA, dossier)
    data = read_json(dossier)
    require(len(data["knowledge_layer"]) >= 1, "knowledge_layer is empty")
    require(len(data["material_layer"]) >= 1, "material_layer is empty")
    require(len(data["slide_layer"]) >= 1, "slide_layer is empty")
    material_paths = {item["path"] for item in data["material_layer"]}
    require("../assets/feishu-deck.js" in material_paths, "HTML script dependency not preserved as material")
    require(data["handoff"]["deck_planner"]["target_skill"] == "deck-planner", "planner handoff missing")


def case_parser_missing_source_corner(_case: dict[str, Any], ctx: Context) -> None:
    out = ctx.root / "parser-missing-source-corner"
    missing = ctx.root / "missing-source.pdf"
    proc = run([
        sys.executable,
        str(PARSER),
        str(missing),
        "--brief",
        "缺失素材测试",
        "--output-dir",
        str(out),
        "--allow-missing",
    ])
    require_proc_ok(proc, "upload-parser missing source")
    dossier = out / "source-dossier.json"
    validate_contract(SOURCE_DOSSIER_SCHEMA, dossier)
    data = read_json(dossier)
    require(data["source_inventory"][0]["exists"] is False, "missing source was not marked exists=false")
    require(any("source not found" in item for item in data["confidence"]["needs_confirmation"]), "missing source gap not surfaced")
    require(data["handoff"]["deck_ingestor"]["ready"] is False, "ingestor handoff should not be ready before audit")


def case_planner_outline_happy(_case: dict[str, Any], ctx: Context) -> None:
    outline = ensure_outline(ctx)
    proc = run([sys.executable, str(OUTLINE_VALIDATOR), "--strict-design", str(outline)])
    require_proc_ok(proc, "validate-outline --strict-design")
    data = read_json(outline)
    for item in data["outline"]["slides"]:
        for field in ["hero", "density_budget", "design_spec", "content_completion", "fact_boundary"]:
            require(field in item, f"{item['key']} missing {field}")


def case_planner_thin_outline_corner(_case: dict[str, Any], ctx: Context) -> None:
    outline = rich_outline()
    del outline["outline"]["slides"][1]["design_spec"]
    path = ctx.root / "planner-thin-outline-corner" / "thin-outline.json"
    write_json(path, outline)
    proc = run([sys.executable, str(OUTLINE_VALIDATOR), "--strict-design", str(path)])
    require_proc_fail(proc, "thin outline strict validation")
    require("design_spec" in proc.stderr, "strict design failure did not mention design_spec")


def case_renderer_compile_render_happy(_case: dict[str, Any], ctx: Context) -> None:
    deck_path, _html_path, out = ensure_rendered(ctx)
    require(deck_path.exists(), "deck.json missing")
    require((out / "index.html").exists(), "index.html missing")
    require((out / "texts.md").exists(), "texts.md missing")
    require((out / "FEEDBACK.md").exists(), "FEEDBACK.md missing")


def case_renderer_invalid_deck_corner(_case: dict[str, Any], ctx: Context) -> None:
    bad = {
        "version": "1.0",
        "deck": {"title": "Bad Deck"},
        "slides": [{"key": "1bad", "layout": "content", "data": {}}],
    }
    path = ctx.root / "renderer-invalid-deck-corner" / "bad-deck.json"
    write_json(path, bad)
    proc = run([sys.executable, str(VALIDATE_DECK), str(path)])
    require_proc_fail(proc, "bad DeckJSON validation")


def case_auditor_rendered_deck_happy(_case: dict[str, Any], ctx: Context) -> None:
    audit_json = ensure_audit(ctx)
    payload = read_json(audit_json)
    require(payload["ingestion_handoff"]["ready"] is True, "auditor did not open ingestion handoff")


def case_auditor_broken_html_corner(_case: dict[str, Any], ctx: Context) -> None:
    out = ctx.root / "auditor-broken-html-corner"
    html = out / "index.html"
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text("<!doctype html><html><body><section class=\"slide\">Bad!</section></body></html>", encoding="utf-8")
    audit_json = out / "audit-report.json"
    proc = run([
        sys.executable,
        str(AUDITOR),
        str(html),
        "--report",
        str(out / "AUDIT_REPORT.md"),
        "--json-report",
        str(audit_json),
        "--h5-report",
        str(out / "H5_CHECKONLY_REPORT.md"),
        "--no-visual",
        "--no-strict",
    ])
    require_proc_fail(proc, "broken HTML audit")
    validate_contract(AUDIT_SCHEMA, audit_json)
    payload = read_json(audit_json)
    require(payload["verdict"] != "pass", "broken HTML unexpectedly passed")
    require(payload["ingestion_handoff"]["ready"] is False, "broken HTML should not be ready for ingestion")


def case_pitch_simulator_happy(_case: dict[str, Any], ctx: Context) -> None:
    deck_path, html_path, _ = ensure_rendered(ctx)
    outline = ensure_outline(ctx)
    out = ctx.root / "pitch-simulator-happy"
    out_json = out / "pitch-rehearsal.json"
    proc = run([
        sys.executable,
        str(SIMULATOR),
        "--outline",
        str(outline),
        "--deck-json",
        str(deck_path),
        "--html",
        str(html_path),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out / "PITCH_REHEARSAL.md"),
        "--meeting-type",
        "POC 启动提案",
    ])
    require_proc_ok(proc, "pitch simulator")
    proc = run([sys.executable, str(VALIDATE_REHEARSAL), str(out_json)])
    require_proc_ok(proc, "pitch rehearsal validation")
    data = read_json(out_json)
    require(len(data["audience_panel"]) >= 3, "audience panel too small")
    require(data["claim_discipline"]["simulated_not_observed"] is True, "simulated result not labelled as simulated")


def case_pitch_invalid_meeting_corner(_case: dict[str, Any], ctx: Context) -> None:
    out = ctx.root / "pitch-invalid-meeting-corner"
    out_json = out / "pitch-rehearsal.json"
    proc = run([
        sys.executable,
        str(SIMULATOR),
        "--out-json",
        str(out_json),
        "--meeting-type",
        "not-a-meeting",
    ])
    require_proc_fail(proc, "pitch simulator invalid meeting type")
    require(not out_json.exists(), "invalid meeting type still produced rehearsal JSON")


def write_pass_audit(path: Path, deck: Path, html: Path) -> None:
    payload = {
        "h5_checkonly_summary": {
            "status": "PASS",
            "errors": 0,
            "warnings": 0,
            "flags": ["no-visual"],
            "exit_code": 0,
            "report_path": "",
            "visual_requested": False,
            "visual_unavailable": False,
        },
        "deck_validation": {"ok": True, "exit_code": 0, "message": ""},
        "sidecars": {},
        "talk_readiness": {},
        "design_readiness": {},
        "interaction_readiness": {},
        "verdict": "pass",
        "blockers": [],
        "warnings": [],
        "routing": {},
        "reuse_assessment": {
            "knowledge_candidate": True,
            "presentation_candidate": True,
            "reason": "contract fixture",
        },
        "ingestion_handoff": {
            "ready": True,
            "reason": "ready for dry-run ingestion",
            "deck_json": str(deck),
            "html": str(html),
            "target_skill": "deck-ingestor",
        },
        "validation": {
            "schema": "skills/lark-deck-cyrus/schema/audit-report.schema.json",
            "validated": False,
        },
    }
    write_json(path, payload)


def case_ingestor_audited_dry_run_happy(_case: dict[str, Any], ctx: Context) -> None:
    deck_path, html_path, _ = ensure_rendered(ctx)
    task_id = f"skill-contract-cases/{ctx.root.name}/ingestor-happy"
    output_dir = REPO / "runs" / task_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(deck_path, output_dir / "deck.json")
    write_pass_audit(output_dir / "audit-report.json", output_dir / "deck.json", html_path)
    proc = run([
        sys.executable,
        str(INGESTOR),
        "--task-id",
        task_id,
        "--title",
        "门店 SOP agent 试点方案",
        "--industry",
        "消费零售",
        "--product",
        "飞书",
        "--dry-run",
    ])
    require_proc_ok(proc, "deck-ingestor dry-run")
    manifest = output_dir / "ingestion-manifest.json"
    validate_contract(INGESTION_SCHEMA, manifest)
    data = read_json(manifest)
    require(data["dry_run"] is True, "manifest dry_run flag not set")
    require(len(data["slide_records"]) >= 1, "no dry-run slide records emitted")
    require(all(item["mode"] == "dry-run" for item in data["slide_records"]), "slide records were not dry-run records")


def case_ingestor_unaudited_corner(_case: dict[str, Any], ctx: Context) -> None:
    deck_path, _html_path, _ = ensure_rendered(ctx)
    task_id = f"skill-contract-cases/{ctx.root.name}/ingestor-unaudited"
    output_dir = REPO / "runs" / task_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(deck_path, output_dir / "deck.json")
    proc = run([sys.executable, str(INGESTOR), "--task-id", task_id, "--dry-run"])
    require_proc_fail(proc, "deck-ingestor unaudited")
    require("deck-auditor pass verdict" in (proc.stderr + proc.stdout), "unaudited failure did not mention auditor pass verdict")


def case_flow_confirmed_pipeline_happy(_case: dict[str, Any], _ctx: Context) -> None:
    proc = run([sys.executable, str(PIPELINE_CONTRACT)], timeout=60)
    require_proc_ok(proc, "confirmed pipeline contract")


def case_flow_plan_only_outline_gate_happy(_case: dict[str, Any], ctx: Context) -> None:
    task = create_generator_plan_task(ctx, "flow-plan-only-outline-gate-happy-task")
    input_dir = Path(task["input_dir"])
    output_dir = Path(task["output_dir"])
    require(task["status"] == "awaiting_outline_confirmation", "plan-only task did not pause after outline")
    require(task.get("confirmation_required") == "outline", "plan-only task did not require outline confirmation")
    require((output_dir / "DESIGN_PLAN.md").exists(), "DESIGN_PLAN.md missing")
    require((input_dir / "outline.json").exists(), "outline.json missing")
    require(not (output_dir / "deck.json").exists(), "deck.json was created before outline confirmation")
    require(not (output_dir / "index.html").exists(), "index.html was created before outline confirmation")
    proc = run([sys.executable, str(OUTLINE_VALIDATOR), "--strict-design", str(input_dir / "outline.json")])
    require_proc_ok(proc, "plan-only outline strict validation")


def case_flow_auto_confirm_plan_only_corner(_case: dict[str, Any], _ctx: Context) -> None:
    proc = run([
        sys.executable,
        str(GENERATOR),
        "create",
        "--request",
        str(GENERATOR_REQUEST),
        "--auto-confirm-outline",
        "--plan-only",
    ], timeout=20)
    require_proc_ok(proc, "generator auto-confirm plan-only")
    task = json.loads(proc.stdout)
    output_dir = Path(task["output_dir"])
    require(task["status"] == "awaiting_outline_confirmation", "plan-only did not override auto-confirm")
    require(not (output_dir / "deck.json").exists(), "plan-only auto-confirm rendered deck.json")


def case_flow_accept_rehearsal_publishes_happy(_case: dict[str, Any], ctx: Context) -> None:
    task = create_generator_accepted_task(ctx, "flow-accept-rehearsal-publishes-happy-task")
    output_dir = Path(task["output_dir"])
    artifacts = task.get("artifacts", {})
    magic_url = artifacts.get("magic_page_url") or ""
    require(magic_url.startswith("https://magic.solutionsuite.cn/dryrun/"), "magic_page_url is not a Magic Page dry-run URL")
    require((output_dir / "magic-page-publish.json").exists(), "magic-page-publish.json missing")
    require((output_dir / "MAGIC_PAGE_PUBLISH.md").exists(), "MAGIC_PAGE_PUBLISH.md missing")
    publish = read_json(output_dir / "magic-page-publish.json")
    require(publish.get("dry_run") is True, "publish artifact did not record dry_run=true")


def case_flow_revise_from_rehearsal_happy(_case: dict[str, Any], ctx: Context) -> None:
    task = create_generator_rehearsal_task(ctx, "flow-revise-from-rehearsal-happy-task")
    proc = run([sys.executable, str(GENERATOR), "revise-from-rehearsal", task["id"]], timeout=45)
    require_proc_ok(proc, "generator revise-from-rehearsal")
    revised = json.loads(proc.stdout)
    require(revised["id"].endswith("-v001"), "revision task id did not end with -v001")
    require(revised.get("parent_task_id") == task["id"], "revision did not retain parent_task_id")
    require(revised.get("source") == "rehearsal-feedback", "revision source was not rehearsal-feedback")
    require(revised["status"] == "awaiting_outline_confirmation", "revision did not return to outline confirmation")
    require(revised.get("confirmation_required") == "outline", "revision did not require outline confirmation")
    output_dir = Path(revised["output_dir"])
    input_dir = Path(revised["input_dir"])
    require((output_dir / "DESIGN_PLAN.md").exists(), "revision DESIGN_PLAN.md missing")
    require((input_dir / "outline.json").exists(), "revision outline.json missing")
    require(not (output_dir / "deck.json").exists(), "revision rendered deck before new outline confirmation")


def case_flow_skip_ingestion_happy(_case: dict[str, Any], ctx: Context) -> None:
    task = create_generator_accepted_task(ctx, "flow-skip-ingestion-happy-task")
    proc = run([sys.executable, str(GENERATOR), "skip-ingest", task["id"]], timeout=30)
    require_proc_ok(proc, "generator skip-ingest")
    skipped = json.loads(proc.stdout)
    require(skipped["status"] == "completed_without_ingestion", "skip-ingest did not complete task")
    require(not skipped.get("confirmation_required"), "skip-ingest left a confirmation gate open")
    require(skipped.get("ingestion", {}).get("skipped") is True, "skip-ingest did not record ingestion.skipped=true")
    require(not (Path(skipped["output_dir"]) / "ingestion-manifest.json").exists(), "skip-ingest wrote an ingestion manifest")


def case_flow_rehearsal_gate_corner(_case: dict[str, Any], ctx: Context) -> None:
    spec = importlib.util.spec_from_file_location("run_cyrus_pipeline_module", PIPELINE)
    require(spec is not None and spec.loader is not None, "cannot load run_cyrus_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out = ctx.root / "flow-rehearsal-gate-corner"
    outline_path = out / "outline.json"
    deck_path = out / "deck.json"
    rehearsal_path = out / "pitch-rehearsal.json"
    write_json(outline_path, {
        "brief": {"title": "中际旭创制造业 AI Agent 提案"},
        "outline": {"slides": [{"key": "npi-agent", "title": "NPI 光模块质量异常 AI 闭环"}]},
    })
    write_json(deck_path, {
        "version": "1.0",
        "deck": {"title": "中际旭创制造业 AI Agent 提案"},
        "slides": [
            {
                "key": "npi-agent",
                "layout": "content",
                "variant": "3up",
                "data": {
                    "title": "中际旭创光模块 NPI 制造业 AI Agent",
                    "cards": [
                        {"title": "质量异常", "body": "工程师需要证据闭环"},
                        {"title": "MES / PLM", "body": "系统边界待确认"},
                        {"title": "大模型", "body": "智能体需要可信证据"},
                    ],
                },
            }
        ],
    })
    write_json(rehearsal_path, {
        "deck_arc": {"scores": {"trust": 50}},
        "outcome_forecast": {"primary_outcome": "request-more-material", "confidence": "medium"},
        "revision_queue": [
            {
                "priority": "P0",
                "owner": "evidence",
                "target": "npi-agent",
                "issue": "缺少证据",
                "change": "补 NPI 异常样例",
            }
        ],
    })
    result = module.evaluate_rehearsal_gate(rehearsal_path, outline_path, deck_path)
    write_json(out / "rehearsal-gate-result.json", result)
    require(result["applied"] is True, "manufacturing AI rehearsal gate did not apply")
    require(result["ok"] is False, "low-trust manufacturing AI rehearsal gate unexpectedly passed")
    require(result["blockers"], "rehearsal gate did not explain blockers")


CASE_FUNCS: dict[str, Callable[[dict[str, Any], Context], None]] = {
    "parser-html-happy": case_parser_html_happy,
    "parser-missing-source-corner": case_parser_missing_source_corner,
    "planner-outline-happy": case_planner_outline_happy,
    "planner-thin-outline-corner": case_planner_thin_outline_corner,
    "renderer-compile-render-happy": case_renderer_compile_render_happy,
    "renderer-invalid-deck-corner": case_renderer_invalid_deck_corner,
    "auditor-rendered-deck-happy": case_auditor_rendered_deck_happy,
    "auditor-broken-html-corner": case_auditor_broken_html_corner,
    "pitch-simulator-happy": case_pitch_simulator_happy,
    "pitch-invalid-meeting-corner": case_pitch_invalid_meeting_corner,
    "ingestor-audited-dry-run-happy": case_ingestor_audited_dry_run_happy,
    "ingestor-unaudited-corner": case_ingestor_unaudited_corner,
    "flow-confirmed-pipeline-happy": case_flow_confirmed_pipeline_happy,
    "flow-plan-only-outline-gate-happy": case_flow_plan_only_outline_gate_happy,
    "flow-auto-confirm-plan-only-corner": case_flow_auto_confirm_plan_only_corner,
    "flow-accept-rehearsal-publishes-happy": case_flow_accept_rehearsal_publishes_happy,
    "flow-revise-from-rehearsal-happy": case_flow_revise_from_rehearsal_happy,
    "flow-skip-ingestion-happy": case_flow_skip_ingestion_happy,
    "flow-rehearsal-gate-corner": case_flow_rehearsal_gate_corner,
}


def load_cases() -> list[dict[str, Any]]:
    data = read_json(CASES_JSON)
    cases = data.get("cases", [])
    require(isinstance(cases, list) and cases, "cases JSON has no cases")
    missing = [case["id"] for case in cases if case["id"] not in CASE_FUNCS]
    require(not missing, "missing runner implementations: " + ", ".join(missing))
    return cases


def write_report(root: Path, rows: list[dict[str, Any]]) -> None:
    ok = all(row["status"] == "PASS" for row in rows)
    lines = [
        "# Cyrus Skill Contract Case Report",
        "",
        f"- status: {'PASS' if ok else 'FAIL'}",
        f"- cases: {len(rows)}",
        f"- artifacts: `{root}`",
        "",
        "| Case | Skill | Path | Status | Seconds | Detail |",
        "|---|---|---:|---|---:|---|",
    ]
    for row in rows:
        detail = str(row.get("detail") or "").replace("\n", "<br>")
        lines.append(
            f"| `{row['id']}` | {row['skill']} | {row['path']} | {row['status']} | {row['seconds']:.2f} | {detail} |"
        )
    lines.append("")
    (root / "EVAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", action="append", default=[], help="Run only this case id. Repeatable.")
    ap.add_argument("--list", action="store_true", help="List case ids and exit.")
    ap.add_argument("--keep-going", action="store_true", help="Continue after a failure.")
    args = ap.parse_args(argv)

    cases = load_cases()
    if args.list:
        for case in cases:
            print(f"{case['id']}\t{case['skill']}\t{case['path']}")
        return 0

    selected = set(args.case)
    if selected:
        known = {case["id"] for case in cases}
        unknown = selected - known
        require(not unknown, "unknown case ids: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in selected]

    run_id = time.strftime("%Y%m%d-%H%M%S")
    ctx = Context(RUNS_ROOT / run_id)
    ctx.root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CASES_JSON, ctx.root / CASES_JSON.name)

    rows: list[dict[str, Any]] = []
    for case in cases:
        start = time.time()
        status = "PASS"
        detail = ""
        try:
            CASE_FUNCS[case["id"]](case, ctx)
        except Exception as exc:  # noqa: BLE001 - test runner should report all failure details.
            status = "FAIL"
            detail = f"{type(exc).__name__}: {exc}"
        rows.append({
            "id": case["id"],
            "skill": case["skill"],
            "path": case["path"],
            "status": status,
            "seconds": time.time() - start,
            "detail": detail,
        })
        print(f"{status} {case['id']} ({rows[-1]['seconds']:.2f}s)")
        if status != "PASS" and not args.keep_going:
            break

    write_report(ctx.root, rows)
    print(f"Report: {ctx.root / 'EVAL_REPORT.md'}")
    return 0 if all(row["status"] == "PASS" for row in rows) and len(rows) == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
