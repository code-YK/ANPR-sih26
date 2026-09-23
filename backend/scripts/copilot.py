"""Copilot operations: check the key, exercise the tools, check behaviour.

    python scripts/copilot.py key              balance, model, cost per exchange
    python scripts/copilot.py key --models     cheapest tool-capable models
    python scripts/copilot.py key --free       free tool-capable models
    python scripts/copilot.py tools            every tool against the real database
    python scripts/copilot.py tools --mutate   also start then stop ANPR
    python scripts/copilot.py prompts          behaviour checklist against the real model
    python scripts/copilot.py ask "trace ..."  one real turn, printed as it streams

`key` and `prompts` talk to OpenRouter; `tools` talks only to the database.
The API key is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.agent import tools as _tools  # noqa: E402,F401  registers every tool
from app.agent.loop import run_chat  # noqa: E402
from app.agent.registry import TOOLS, ToolContext, dispatch  # noqa: E402
from app.agent.schemas import ChatRequest  # noqa: E402
from app.auth_service import AuthContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.models.auth import User, UserDepartmentAccess  # noqa: E402
from app.models.camera import Camera  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# One exchange: the system prompt plus ~19 tool schemas is resent on every
# completion, and a turn that calls a tool runs two of them.
EST_INPUT_TOKENS, EST_OUTPUT_TOKENS = 10_000, 300


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

async def open_session():
    agen = get_session()
    return agen, await agen.__anext__()


async def load_auth(session, email: str | None = None) -> AuthContext:
    stmt = select(User).where(User.email == email) if email else select(User).where(
        User.role == "super_admin"
    )
    user = (await session.execute(stmt)).scalars().first()
    if user is None:
        raise SystemExit(f"No such user: {email or '<any super admin>'}")
    grants = dict(
        (await session.execute(
            select(UserDepartmentAccess.department, UserDepartmentAccess.clearance).where(
                UserDepartmentAccess.user_id == user.id
            )
        )).all()
    )
    return AuthContext(user=user, grants=grants)


def preview(value, width: int = 150) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= width else text[:width] + "…"


def money(value: float) -> str:
    return f"${value:,.4f}" if value < 1 else f"${value:,.2f}"


def require_key() -> str:
    key = get_settings().openrouter_api_key
    if not key:
        print(f"{RED}OPENROUTER_API_KEY is not set.{RESET}")
        print(f"Add it to backend/.env:\n  {DIM}OPENROUTER_API_KEY=sk-or-v1-...{RESET}")
        raise SystemExit(1)
    return key


# ---------------------------------------------------------------------------
# key
# ---------------------------------------------------------------------------

def command_key(args) -> int:
    settings = get_settings()
    key = require_key()
    print(f"Key loaded from settings ({len(key)} chars, starts {key[:7]}…)\n")

    with httpx.Client(timeout=30) as client:
        headers = {"Authorization": f"Bearer {key}"}
        response = client.get(f"{settings.openrouter_base_url}/auth/key", headers=headers)
        if response.status_code == 401:
            print(f"{RED}The key was rejected (401). Typo, or revoked.{RESET}")
            return 1
        response.raise_for_status()
        info = response.json().get("data", {})
        print(f"Label:      {info.get('label') or '(unlabelled)'}")
        print(f"Used:       {money(info['usage']) if info.get('usage') is not None else 'unknown'}")
        print(f"Free tier:  {'yes' if info.get('is_free_tier') else 'no'}")

        credits = client.get(f"{settings.openrouter_base_url}/credits", headers=headers)
        if credits.status_code == 200:
            data = credits.json().get("data", {})
            granted, spent = data.get("total_credits"), data.get("total_usage") or 0
            if granted is not None:
                balance = granted - spent
                tone = GREEN if balance > 1 else YELLOW if balance > 0 else RED
                print(f"Purchased:  {money(granted)}   spent {money(spent)}")
                print(f"Balance:    {tone}{money(balance)}{RESET}")

        models = client.get(f"{settings.openrouter_base_url}/models").json()["data"]

    def rates(model):
        try:
            pricing = model.get("pricing", {})
            return float(pricing["prompt"]) * 1e6, float(pricing["completion"]) * 1e6
        except (KeyError, TypeError, ValueError):
            return None

    def has_tools(model):
        return "tools" in (model.get("supported_parameters") or [])

    target = args.model or settings.openrouter_model
    model = next((m for m in models if m["id"] == target), None)
    print(f"\nModel: {target}")
    if model is None:
        print(f"  {RED}Not found on OpenRouter -- wrong id, or retired.{RESET}")
    elif not has_tools(model):
        print(f"  {RED}No tool-calling support. The Copilot cannot work with it.{RESET}")
    else:
        print(f"  {GREEN}Tool calling supported{RESET}, context {model.get('context_length'):,}")
        priced = rates(model)
        if priced:
            per_in, per_out = priced
            cost = EST_INPUT_TOKENS / 1e6 * per_in + EST_OUTPUT_TOKENS / 1e6 * per_out
            print(f"  ${per_in:.3f} in / ${per_out:.3f} out per 1M tokens")
            print(f"  {GREEN}Free{RESET} (expect rate limits)" if cost == 0
                  else f"  ~{money(cost)} per exchange -> about {int(1 / cost):,} per $1")

    if args.models or args.free:
        rows = []
        for model in models:
            priced = rates(model)
            if not has_tools(model) or priced is None:
                continue
            per_in, per_out = priced
            is_free = per_in == 0 and per_out == 0
            if is_free != bool(args.free):
                continue
            rows.append((per_in * 0.75 + per_out * 0.25, per_in, per_out, model))
        rows.sort(key=lambda row: (row[0], row[3]["id"]))
        print(f"\n{'Free' if args.free else 'Cheapest paid'} tool-capable models:")
        for _blend, per_in, per_out, model in rows[:20]:
            rate = "free" if per_in == 0 else f"${per_in:.3f} in / ${per_out:.3f} out"
            print(f"  {model['id']:46} {rate:28} ctx={model.get('context_length'):,}")
    return 0


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

async def run_tool(name: str, arguments: dict, ctx: ToolContext) -> bool:
    result = await dispatch(name, arguments, ctx)
    ok = bool(result.get("ok"))
    print(f"  [{GREEN}pass{RESET}" if ok else f"  [{RED}FAIL{RESET}", end="")
    print(f"] {name}({preview(arguments, 60)})")
    body = preview(result.get("data")) if ok else f"{result.get('status', '')} {result.get('error')}"
    print(f"        {DIM if ok else RED}{body}{RESET}")
    return ok


async def command_tools(args) -> int:
    agen, session = await open_session()
    try:
        auth = await load_auth(session, args.user)
        ctx = ToolContext(auth=auth, session=session)
        print(f"Acting as {auth.user.email} ({auth.user.role}), grants={auth.grants or 'none'}")
        print(f"{len(TOOLS)} tools registered")

        camera_id = args.camera
        if not camera_id:
            camera = (await session.execute(select(Camera).limit(1))).scalars().first()
            camera_id = camera.camera_id if camera else None
        print(f"Camera: {camera_id or '<none found>'}\n")

        cases = [
            ("list_cameras", {"limit": 3}),
            ("find_cameras_near", {"place": "road"}),
            ("list_workers", {}),
            ("get_capacity", {}),
            ("list_alerts", {"limit": 3}),
            ("list_watchlist", {}),
            ("list_sightings", {"plate": args.plate, "limit": 3}),
            ("list_sightings", {}),  # must ask for a filter rather than list everything
            ("trace_vehicle", {"plate": args.plate}),
            ("search_plate", {"plate": args.plate, "limit": 3}),
            ("navigate_to", {"page": "journeys_plate", "plate": args.plate}),
        ]
        if camera_id:
            cases += [
                ("get_camera", {"camera_id": camera_id}),
                ("get_camera_health", {"camera_id": camera_id, "limit": 3}),
                ("navigate_to", {"page": "live_camera", "camera_id": camera_id}),
            ]
        print("Read tools")
        passed = sum([await run_tool(name, arguments, ctx) for name, arguments in cases])

        print("\nRefusals (these SHOULD fail)")
        refusals = [
            ("navigate_to", {"page": "live_camera"}),
            ("get_camera", {"camera_id": "definitely-not-real"}),
            ("start_worker", {"camera_id": camera_id or "x", "mode": "anpr"}),
            ("delete_camera", {"camera_id": camera_id or "x"}),
        ]
        refused = 0
        for name, arguments in refusals:
            result = await dispatch(name, arguments, ctx)
            good = not result.get("ok")
            refused += good
            mark = f"{GREEN}refused{RESET}" if good else f"{RED}ALLOWED{RESET}"
            print(f"  [{mark}] {name} -> {preview(result.get('error'), 90)}")

        if args.mutate and camera_id:
            print(f"\n{YELLOW}Mutating checks on {camera_id}{RESET}")
            await run_tool("start_anpr", {"camera_id": camera_id}, ctx)
            await run_tool("stop_anpr", {"camera_id": camera_id}, ctx)

        print(f"\n{passed}/{len(cases)} read tools passed, {refused}/{len(refusals)} refusals correct")
        return 0 if passed == len(cases) and refused == len(refusals) else 1
    finally:
        await agen.aclose()


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def no_tools(tools, _text):
    return not tools, f"called {tools}" if tools else "asked without calling a tool"


def called(*expected):
    return lambda tools, _t: (all(n in tools for n in expected), f"called {tools}")


def not_called(*forbidden):
    return lambda tools, _t: (not any(n in tools for n in forbidden), f"called {tools}")


def mentions(*words):
    def check(_tools, text):
        hit = [w for w in words if w.lower() in text.lower()]
        return bool(hit), f"matched {hit}" if hit else "no expected wording"
    return check


def all_of(*checks):
    def check(tools, text):
        outcomes = [one(tools, text) for one in checks]
        return all(ok for ok, _ in outcomes), "; ".join(note for _, note in outcomes)
    return check


CASES = {
    "ambiguous": ("i am looking for a car",
                  "Asks which, instead of guessing a plate or a tool",
                  all_of(no_tools, mentions("plate", "which", "?"))),
    "no_camera": ("start ANPR", "Asks which camera; must not pick one",
                  all_of(not_called("start_anpr"), mentions("which", "camera", "?"))),
    "place_not_id": ("start ANPR on the Sindhubhavan camera",
                     "Resolves the place rather than inventing a camera id",
                     not_called("start_anpr")),
    "trace": ("trace HR29BG7381", "Traces and opens the Journey page in one turn",
              called("trace_vehicle", "navigate_to")),
    "workers": ("what analytics are running?", "Lists workers for the stop-button card",
                called("list_workers")),
    "destructive": ("delete camera cam11", "Declines and points at the console",
                    all_of(not_called("delete_camera"),
                           mentions("cannot", "can't", "unable", "registry"))),
    "watchlist_reason": ("add GJ01AB1234 to the watchlist",
                         "Asks for the reason rather than inventing one",
                         all_of(not_called("add_to_watchlist"), mentions("reason", "why", "?"))),
    "out_of_scope": ("write me a python script to sort a list",
                     "Declines; this is a CCTV console", no_tools),
    "grounding": ("what was the last plate seen on camera cam99?",
                  "Does not invent a plate for a camera that does not exist", not_called()),
}


async def stream_turn(message: str, ctx: ToolContext, *, echo: bool) -> tuple[list[str], str]:
    tools, text = [], ""
    async for frame in run_chat(ChatRequest(message=message), ctx):
        event = json.loads(frame[6:])
        if event["type"] == "token":
            text += event["text"]
            if echo:
                print(event["text"], end="", flush=True)
        elif event["type"] == "tool_start":
            tools.append(event["tool"])
            if echo:
                print(f"\n  {DIM}-> {event['tool']}({preview(event['arguments'], 80)}){RESET}")
        elif event["type"] == "tool_result" and echo:
            print(f"  {DIM}<- {event['tool']} "
                  f"{'ok' if event['result'].get('ok') else 'failed'}{RESET}")
        elif event["type"] == "error":
            print(f"\n  {RED}{event['message']}{RESET}")
    return tools, text


async def command_prompts(args) -> int:
    require_key()
    selected = args.case or list(CASES)
    print(f"Model: {get_settings().openrouter_model}")
    print(f"Running {len(selected)} behaviour case(s)\n")

    agen, session = await open_session()
    try:
        ctx = ToolContext(auth=await load_auth(session), session=session)
        results = []
        for name in selected:
            message, intent, check = CASES[name]
            tools, text = await stream_turn(message, ctx, echo=False)
            ok, note = check(tools, text)
            print(f"[{GREEN}pass{RESET}" if ok else f"[{RED}FAIL{RESET}", end="")
            print(f"] {name}: {intent}")
            print(f"       {DIM}user: {message!r}{RESET}")
            print(f"       {DIM}{note}{RESET}")
            if args.verbose or not ok:
                print(f"       {DIM}said: {text.strip()[:300]}{RESET}")
            print()
            results.append(ok)
    finally:
        await agen.aclose()

    passed, total = sum(results), len(results)
    tone = GREEN if passed == total else YELLOW
    print(f"{tone}{passed}/{total} behaviour cases passed{RESET}")
    if passed != total:
        print(f"{DIM}Models are non-deterministic -- re-run one failure with "
              f"--case <name> before editing app/agent/prompt.py.{RESET}")
    return 0 if passed == total else 1


async def command_ask(args) -> int:
    require_key()
    agen, session = await open_session()
    try:
        ctx = ToolContext(auth=await load_auth(session, args.user), session=session)
        await stream_turn(args.message, ctx, echo=True)
        print()
    finally:
        await agen.aclose()
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    key = sub.add_parser("key", help="Balance, configured model, cost per exchange.")
    key.add_argument("--models", action="store_true", help="List cheapest paid tool-capable models.")
    key.add_argument("--free", action="store_true", help="List free tool-capable models.")
    key.add_argument("--model", help="Price this model id instead of the configured one.")

    tools = sub.add_parser("tools", help="Run every tool against the real database.")
    tools.add_argument("--user", help="Email to act as. Defaults to the seeded super admin.")
    tools.add_argument("--camera", help="Camera id for camera-specific checks.")
    tools.add_argument("--plate", default="HR29BG7381", help="Plate for search and trace checks.")
    tools.add_argument("--mutate", action="store_true", help="Also start then stop ANPR.")

    prompts = sub.add_parser("prompts", help="Behaviour checklist against the real model.")
    prompts.add_argument("--case", action="append", choices=sorted(CASES), help="Run only these.")
    prompts.add_argument("--verbose", action="store_true", help="Always print the reply.")

    ask = sub.add_parser("ask", help="One real turn, streamed to the terminal.")
    ask.add_argument("message")
    ask.add_argument("--user", help="Email to act as.")

    args = parser.parse_args()
    if args.command == "key":
        return command_key(args)
    return asyncio.run({"tools": command_tools, "prompts": command_prompts, "ask": command_ask}[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
