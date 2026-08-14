"""
to prove tools and the database works, imports agent

calls for the three no risk tools without the need for the DeepSeek API key

"""

import json
import agent

def show(title, value):
    print(f"\n {title}")
    print(json.dumps(value, indent=2, default=str)[:1400])

if __name__ == "__main__":
    show(
        "check_stock(stock_keeping_unit='HL-THROW-01')",
        agent.check_stock(stock_keeping_unit="HL-THROW-01")
    )

    low = agent.find_low_inventory(days_of_cover_threshold=14)

    print(f"\nfind_low_inventory: {low['flagged_count']} flagged")

    for it in low["flagged"]:
        #left aligning with character space
        print(
            f" {it['stock_keeping_unit']:<14} "
            f" on_hand={it['on_hand']:<4} "
            f" cover={it['days_of_cover']}d "
            f" {it['severity']} "
            f" {it['reasons']}"
        )

    show("calculate_reorder('HL-THROW-01)", agent.calculate_reorder('HL-THROW-01'))

    print("\nRead tools")
