"""
This is the agent python script
Its handwritten on top of DeepSeek's chat-completions API
The loop is:
    1. send convo and tool schemas to model
    2. model runs tool calls is asked for them and appends the results
    3. model replies with text and prints
Tools are (check_stock, find_low_inventory, calculate_reorder)
These are all read only
The place_purchase_order is high risk and requires human approval
The agent is a manual loop
"""


#for a postponed evaluation of annotations
from __future__ import annotations 
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(HERE, "inventory.db")
LOG_PATH = os.path.join(HERE, "agent_log.json1")

MODEL  = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "12"))
PURCHASE_ORDER_APPROVAL_ALWAYS = True

#logging for every tool call (whats returned and the arguements)

#append to agent log json and echo a summary
def log_event(kind: str, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

def log_tool_call(name: str, args: dict, result) -> None:
    log_event("tool_call", tool=name, arguments=args, result=result)
    preview = json.dumps(result, default=str)
    if len(preview) > 500:
        preview = preview[:500] + "...(removed)"
    print(f"\n [TOOL] {name}({json.dumps(args)})")
    print(f" [ -> ] {preview}")

#database helpers
def db() -> sqlite3.Connection:
    if not os.path.exists(DATABASE_PATH):
        raise SystemExit("Inventory database file not found. Make sure to run seed.py")
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def daily_velocity(conn: sqlite3.Connection, stock_keeping_unit: str, window_days: int = 30) -> float:
    #Average units sold per day over a trailing window (fake sales).
    row = conn.execute(
        """
        SELECT COALESCE(SUM(units), 0) AS total
        FROM sales
        WHERE stock_keeping_unit = ?
            AND sold_on >= date('now', ?)
        """,
        (stock_keeping_unit, f"-{window_days} day")
    ).fetchone()
    return round(row["total"] / window_days, 3) 

'''
checking stock will connect to the database, build the query, add stock keeping unit 
and category filters, execute the sql and get each product (inventory, )
'''
def check_stock(stock_keeping_unit: str | None = None, category: str | None = None) -> dict:
    conn = db()
    sql = """
            SELECT  p.stock_keeping_unit, p.name, p.category, p.supplier, p.lead_time_days,
                    p.safety_stock, p.unit_cost, i.on_hand, i.on_order, i.last_counted
            FROM products p JOIN inventory i on i.stock_keeping_unit = p.stock_keeping_unit 
    """
    where, params = [], []
    if stock_keeping_unit:
        where.append("p.stock_keeping_unit = ?")
        params.append(stock_keeping_unit.upper())
    if category:
        where.append("LOWER(p.category) = LOWER(?)")
        params.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.stock_keeping_unit"

    items = []
    for r in conn.execute(sql, params):
        vel = daily_velocity(conn, r["stock_keeping_unit"])
        items.append(
            {
                "stock_keeping_unit": r["stock_keeping_unit"],
                "name": r["name"],
                "category": r["category"],
                "supplier": r["supplier"],
                "on_hand": r["on_hand"],
                "on_order": r["on_order"],
                "safety_stock": r["safety_stock"],
                "lead_time_days": r["lead_time_days"],
                "unit_cost": r["unit_cost"],
                "avg_units_sold_per_day": vel,
                "days_of_cover": round((r["on_hand"] + r["on_order"]) / vel, 1) if vel else None,
            }
        )
    conn.close()
    return {"count": len(items), "items": items}


#finding low inventory tool 
def find_low_inventory(days_of_cover_threshold: float = 14) -> dict:
    data = check_stock()
    flagged = []
    for it in data["items"]:
        cover = it["days_of_cover"]
        below_safety = it["on_hand"] < it["safety_stock"]
        below_cover = cover is not None and cover <= days_of_cover_threshold
        if below_safety or below_cover:
            flagged.append(
                {
                    **it,
                    "reasons": (
                        (["below_safety_stock"] if below_safety else [])
                        + ([f"cover<={days_of_cover_threshold}d"] if below_cover else [])
                    ),
                    "severity": "critical" if below_safety and below_cover else "warning",
                }
            )
    flagged.sort(key=lambda x: (x["days_of_cover"] is None, x["days_of_cover"] or 0))
    return {"threshold_days": days_of_cover_threshold, "flagged_count": len(flagged), "flagged": flagged}

#calculating reorders
def calculate_reorder(stock_keeping_unit: str, target_days_of_cover: float = 30) -> dict:
    data = check_stock(stock_keeping_unit=stock_keeping_unit)
    if not data["items"]:
        return {"error": f"Unknown Stock Keeping Unit: {stock_keeping_unit}"}
    it = data["items"][0]
    vel = it["avg_units_sold_per_day"] or 0.0
    demand_during_lead = vel * it["lead_time_days"]
    target_stock = vel * target_days_of_cover + it["safety_stock"]
    available = it["on_hand"] + it["on_order"]
    raw = target_stock + demand_during_lead - available
    units = max(0, int(round(raw)))
    return {
        "stock_keeping_unit": it["stock_keeping_unit"],
        "name": it["name"],
        "supplier": it["supplier"],
        "on_hand": it["on_hand"],
        "on_order": it["on_order"],
        "avg_units_sold_per_day": vel,
        "lead_time_days": it["lead_time_days"],
        "safety_stock": it["safety_stock"],
        "target_days_of_cover": target_days_of_cover,
        "formula": "units = max(0, velocity*target_days + safety_stock + velocity*lead_time - (on_hand+on_order))",
        "recommended_order_units": units,
        "estimated_cost": round(units * it["unit_cost"], 2),
    }

'''
This is the high risk took which is purchasing the order and writes
'''

def place_purchase_order(stock_keeping_unit: str, units: int, note: str = "") -> dict:
    """Commits real spend and mutates the database. Requires human approval."""
    conn = db()
    row = conn.execute(
        "SELECT p.*, i.on_hand, i.on_order FROM products p JOIN inventory i ON i.stock_keeping_unit=p.stock_keeping_unit WHERE p.stock_keeping_unit=?",
        (stock_keeping_unit.upper(),),
    ).fetchone()
    if row is None:
        conn.close()
        return {"error": f"Unknown Unit: {stock_keeping_unit}"}
    if units <= 0:
        conn.close()
        return {"error": "units must be a positive integer"}

    total = round(units * row["unit_cost"], 2)

    # ---------------- CHECKPOINT: explicit human approval ----------------
    print("\n" + "=" * 66)
    print("  HUMAN APPROVAL REQUIRED — IRREVERSIBLE ACTION")
    print("=" * 66)
    print(f"  Action    : place purchase order (writes to purchase_orders)")
    print(f"  stock_keeping_unit       : {row['stock_keeping_unit']}  ({row['name']})")
    print(f"  Supplier  : {row['supplier']}   lead time {row['lead_time_days']}d")
    print(f"  Units     : {units} @ ${row['unit_cost']:.2f}")
    print(f"  Total     : ${total:,.2f}")
    print(f"  On hand   : {row['on_hand']} (on order {row['on_order']})")
    if note:
        print(f"  Agent note: {note}")
    print("-" * 66)
    answer = input("  Type APPROVE to commit, anything else to cancel: ").strip()
    approved = answer == "APPROVE"
    log_event(
        "approval_checkpoint",
        tool="place_purchase_order",
        stock_keeping_unit=row["stock_keeping_unit"],
        units=units,
        total_cost=total,
        response=answer,
        approved=approved,
    )
    if not approved:
        conn.close()
        return {
            "status": "cancelled_by_human",
            "stock_keeping_unit": row["stock_keeping_unit"],
            "units": units,
            "message": "Human denied approval. No purchase order was created and nothing was written.",
        }
    # ---------------------------------------------------------------------

    who = os.environ.get("APPROVER_NAME", "store_manager")
    cur = conn.execute(
        """INSERT INTO purchase_orders (stock_keeping_unit, supplier, units, unit_cost, total_cost, status, created_at, approved_by)
           VALUES (?,?,?,?,?,'submitted',?,?)""",
        (row["stock_keeping_unit"], row["supplier"], units, row["unit_cost"], total,
         datetime.now(timezone.utc).isoformat(), who),
    )
    conn.execute("UPDATE inventory SET on_order = on_order + ? WHERE stock_keeping_unit = ?", (units, row["stock_keeping_unit"]))
    conn.commit()
    po_id = cur.lastrowid
    conn.close()
    return {
        "status": "submitted",
        "purchase_order_id": po_id,
        "stock_keeping_unit": row["stock_keeping_unit"],
        "supplier": row["supplier"],
        "units": units,
        "total_cost": total,
        "approved_by": who,
    }

#tools and JSON schemas for model to see

TOOL_IMPLS = {
    "check_stock": check_stock,
    "find_low_inventory": find_low_inventory,
    "calculate_reorder": calculate_reorder,
    "place_purchase_order": place_purchase_order,
}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": (
                "Read current stock levels from the inventory database. Returns on-hand units, "
                "units already on order, safety stock, supplier lead time, 30-day average daily "
                "sales velocity and days of cover. Omit both arguments to get the whole catalog."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_keeping_unit": {"type": "string", "description": "Exact Unit, e.g. HL-MUG-01."},
                    "category": {"type": "string", "description": "Category filter, e.g. Kitchen."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_low_inventory",
            "description": (
                "Flag products that are running low: on-hand below safety stock, or projected "
                "days of cover at or below the threshold. Returns each item with reasons and severity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_of_cover_threshold": {
                        "type": "number",
                        "description": "Flag items with this many days of cover or fewer. Default 14.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_reorder",
            "description": (
                "Calculate the recommended reorder quantity and estimated cost for one SKU, using "
                "sales velocity, supplier lead time, safety stock and a target days-of-cover."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_keeping_unit": {"type": "string", "description": "Exact Unit to calculate for."},
                    "target_days_of_cover": {
                        "type": "number",
                        "description": "How many days of stock to hold after delivery. Default 30.",
                    },
                },
                "required": ["stock_keeping_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_purchase_order",
            "description": (
                "HIGH RISK AND IRREVERSIBLE: commits money with a supplier and writes a purchase "
                "order to the database. A human must type APPROVE at a terminal checkpoint before "
                "it runs. Only call this after calculate_reorder and after the user has clearly "
                "asked to order this Unit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_keeping_unit": {"type": "string", "description": "Exact Unit to order."},
                    "units": {"type": "integer", "description": "Number of units to order (positive)."},
                    "note": {"type": "string", "description": "Short justification shown to the approver."},
                },
                "required": ["stock_keeping_unit", "units"],
            },
        },
    },
]

#writing the system prompt
SYSTEM_PROMPT = """You are the inventory assistant for "Home Luxe", a small retail home-goods shop.

You help the store manager check stock, flag low inventory, and size reorders.

Instructions:
- Never guess numbers, always get them from tools.
- Work step by step: find what is low, then calculate reorder per stock keeping unit
- place_purchase_order spends real money and can't be undone. Only call it whenthe manager explicitly asks to order something, and always calculate_reorder first so the quantity is justified. Never batch-order the whole catalog on your own initiative.
- If a purchase order is cancelled by the human, accept it and do not retry.
- Answer in short plain sentences, using compact tables or bullets, and always cite the numbers you used (on hand, velocity, days of cover).
"""

#manual agent loop

def make_client() -> OpenAI:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK API KEY IS NOT SET")
    return OpenAI(api_key=key, base_url=BASE_URL)

def run_agent(client: OpenAI, messages: list[dict]) -> str:
    """keep calling tools until model produces final answer"""
    for step in range(1, MAX_STEPS +1):
        log_event("model_request", step=step, message_count=len(messages))
        response = client.chat.completions.create(

            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS, 
            tool_choice="auto",
            temperature=0.2 #consistent and reliable is what I want this agent to be
        )
        msg = response.choices[0].message

        #ending loop with no tool calls
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            log_event("final_anser", step=step, content=msg.content)
            return msg.content or "(no content)"

        #recording the tool-call turn exactly how it is
        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        #execute requested tools, observe, and feed back result

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            impl = TOOL_IMPLS.get(name)
            if impl is None: 
                result = {"error": f"Unkown tool: {name}"}

            else: 
                try:
                    result = impl(**args)
                except Exception as exc: #don't crash!

                    result = {"error": f"{type(exc).__name__}: {exc}"}
            log_tool_call(name, args, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result, default=str),     
                }
            )

    log_event("loop_limit_reached", max_steps=MAX_STEPS)
    return f"Stopped after {MAX_STEPS} steps with no final answer"

def main() -> None:
    client = make_client()
    messages: list[dict]  = [{"role": "system", "content": SYSTEM_PROMPT}]
    log_event("session_start", model=MODEL, db=DATABASE_PATH)

    if len(sys.argv) >1: #one-shot
        prompt = " ".join(sys.argv[1:])
        print(f"\nYou: {prompt}")
        messages.append({"role": "user", "content": prompt})
        print(f"\nAgent: {run_agent(client, messages)}\n")
        return
    print("Home Luxe Inventory Assistant. Ctrl-C or 'exit' to quit.")
    print('Try: "What is low right now" /   "size a reorder for HL-THROW-01"')

    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return
        if prompt.lower() in {"exit", "quit"}:
            print("Bye!")
            return
        if not prompt:
            continue
        messages.append({"role": "user", "content": prompt})
        print(f"\nAgent: {run_agent(client, messages)}")

if __name__ == "__main__":
    main()
