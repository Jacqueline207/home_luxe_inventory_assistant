# Inventory Assistant Assignment

This AI agent checks for stock levels, it flags low inventory, calculates reorder amounts, and can place a purchase order after requirements are met.


I am building this project with a handwritten agent loop on top of DeepSeek's chat completions API. I am also using SQLite database consisting of synthetic data

---

## 1. What this folder includes

| File | Content |
|---|---|
| `seed_db.py` | creates the inventory database and populates it with fictional data (products and stock levels). It also includes 60 days of fictional sales |
| `agent.py` | has the agent loop, logging, and an approval checkpoint |
| `test_tools_offline.py` | to verify the logic of the sql queries |
| `requirements.txt` | is dependent on openai SDK, compatible with DeepSeek |
| `inventory.db` | is created by the seed file and in order to re-seed should be deleted |
| `agent_log.jsonl` | this file is created on the first run, its one JSON object per the event |

---

## 2. How to setup

**Step 1: After setting up the virtual environment, install the dependency on requirements.txt**

**Step 2: Run python seed.py**

This step will create the inventory database which should contain products, fake sales, and no purchase orders

**Step 3: check tools first without needing an API key**

In order to prove the database and math work before making calls, run test_tools_offline.py

**Step 4: run agent script after adding your API key to a .env file**

Can ask a one-shot question such as "What is low right now?"

```
Other possible questions:

Show me everything in the kitchen category.

Which low item in most urgent, and how many should I order?

Order plenty mugs (this triggers an approval checkpoint)
```

At a checkpoint, anything other than `APPROVE` will cancel

To run the agent: `python agent.py "Your question here"  ` or simply `python agent.py`


