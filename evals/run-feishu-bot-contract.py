#!/usr/bin/env python3
"""Smoke-test the Feishu bot MVP without calling Feishu APIs."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))
os.environ.setdefault("CYRUS_MAGIC_DRY_RUN", "1")
os.environ.setdefault("CYRUS_PUBLISH_TARGET", "magic-page")
os.environ.setdefault("GENERATOR_VISUAL_AUDIT", "0")

import feishu_bot  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        state = feishu_bot.load_state(state_path)

        first = feishu_bot.handle_message_text(
            "帮我做一份示例客户的 AI 知识库 pitchdeck",
            state,
            conversation_key="chat:user",
            base_url="http://127.0.0.1:8765",
        )
        if not first.asked_questions or not (3 <= len(first.asked_questions) <= 5):
            print("bot did not ask 3-5 high-value questions", file=sys.stderr)
            print(first.reply, file=sys.stderr)
            return 1
        feishu_bot.save_state(state, state_path)

        state = feishu_bot.load_state(state_path)
        second = feishu_bot.handle_message_text(
            "\n".join(
                [
                    "消费零售",
                    "COO、运营负责人和信息化负责人",
                    "推动客户确认门店 SOP 试点",
                    "飞书 AI、知识问答、多维表格、飞书任务",
                    "无",
                ]
            ),
            state,
            conversation_key="chat:user",
            base_url="http://127.0.0.1:8765",
        )
        if not second.task or second.task.get("status") != "awaiting_outline_confirmation":
            print("bot did not stop for outline confirmation", file=sys.stderr)
            print(second.reply, file=sys.stderr)
            return 1
        for phrase in ["状态页", "大纲", "确认这个框架"]:
            if phrase not in second.reply:
                print(f"outline reply missing {phrase}", file=sys.stderr)
                print(second.reply, file=sys.stderr)
                return 1
        feishu_bot.save_state(state, state_path)

        state = feishu_bot.load_state(state_path)
        third = feishu_bot.handle_message_text(
            "确认",
            state,
            conversation_key="chat:user",
            base_url="http://127.0.0.1:8765",
        )
        if not third.task or third.task.get("status") != "awaiting_rehearsal_decision":
            print("bot did not stop for rehearsal decision", file=sys.stderr)
            print(third.reply, file=sys.stderr)
            return 1
        for phrase in ["状态页", "飞书妙笔页面", "预演报告", "回复“修改”", "回复“不用改”"]:
            if phrase not in third.reply:
                print(f"rehearsal decision reply missing {phrase}", file=sys.stderr)
                print(third.reply, file=sys.stderr)
                return 1
        feishu_bot.save_state(state, state_path)

        state = feishu_bot.load_state(state_path)
        fourth = feishu_bot.handle_message_text(
            "不用改",
            state,
            conversation_key="chat:user",
            base_url="http://127.0.0.1:8765",
        )
        if not fourth.task or fourth.task.get("status") != "awaiting_deck_confirmation":
            print("bot did not move to ingestion confirmation", file=sys.stderr)
            print(fourth.reply, file=sys.stderr)
            return 1
        for phrase in ["现在确认是否入库", "确认入库", "不入库"]:
            if phrase not in fourth.reply:
                print(f"ingestion confirmation reply missing {phrase}", file=sys.stderr)
                print(fourth.reply, file=sys.stderr)
                return 1
        feishu_bot.save_state(state, state_path)

        state = feishu_bot.load_state(state_path)
        fifth = feishu_bot.handle_message_text(
            "确认",
            state,
            conversation_key="chat:user",
            base_url="http://127.0.0.1:8765",
        )
        if not fifth.task or fifth.task.get("status") != "succeeded":
            print("bot did not ingest the confirmed deck", file=sys.stderr)
            print(fifth.reply, file=sys.stderr)
            return 1
        for phrase in ["状态页", "飞书妙笔页面", "预演报告", "入库报告"]:
            if phrase not in fifth.reply:
                print(f"bot reply missing {phrase}", file=sys.stderr)
                print(fifth.reply, file=sys.stderr)
                return 1
        feishu_bot.save_state(state, state_path)
        if feishu_bot.load_state(state_path).get("pending"):
            print("bot pending state was not cleared", file=sys.stderr)
            return 1
        journey = json.loads((Path(fifth.task["output_dir"]) / "journey.json").read_text(encoding="utf-8"))
        stages = [event.get("stage") for event in journey.get("events", [])]
        if "bot_clarification_asked" not in stages or "bot_brief_completed" not in stages:
            print("bot interaction history was not written to journey", file=sys.stderr)
            return 1

    print(fifth.task["output_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
