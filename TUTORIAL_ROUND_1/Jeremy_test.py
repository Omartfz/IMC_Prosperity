from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json

class Trader:

    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }
    DEFAULT_LIMIT = 50

    EMA_ALPHA = {
        "TOMATOES": 0.20,
    }

    def _safe_load_data(self, raw_data: str):
        if not raw_data:
            return {}
        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            return {}

    def _update_ema(self, data: dict, product: str, new_price: float) -> float:
        alpha = self.EMA_ALPHA.get(product, 0.10)
        key = f"ema_{product}"
        prev_ema = data.get(key, new_price)
        ema = alpha * new_price + (1 - alpha) * prev_ema
        data[key] = ema
        return ema

    def _compute_fair_value(self, product: str, order_depth: OrderDepth, data: dict) -> float:
        bid_wall = min(order_depth.buy_orders.keys())
        ask_wall = max(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        wall_mid = (bid_wall + ask_wall) / 2.0
        tob_mid  = (best_bid + best_ask) / 2.0

        if product == "EMERALDS":
            # Original strategy: wall mid, no EMA, no history
            return wall_mid

        if product == "TOMATOES":
            # EMA of top-of-book mid for mean reversion
            return self._update_ema(data, product, tob_mid)

        # Default: wall mid (original behavior)
        return wall_mid

    def run(self, state: TradingState):
        data = self._safe_load_data(state.traderData)
        passive_quote_cap = 10
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            fair_value = self._compute_fair_value(product, order_depth, data)

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())

            print(f"[{product}] fair={fair_value:.2f}, best_bid={best_bid}, best_ask={best_ask}")

            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, self.DEFAULT_LIMIT)
            max_buy  = limit - position
            max_sell = limit + position
            buy_volume_used  = 0
            sell_volume_used = 0

            # TAKING LEG
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price < fair_value:
                    ask_volume = abs(order_depth.sell_orders[ask_price])
                    buy_qty = min(ask_volume, max_buy - buy_volume_used)
                    if buy_qty > 0:
                        orders.append(Order(product, ask_price, buy_qty))
                        buy_volume_used += buy_qty
                        print(f"  BUY  {buy_qty}x at {ask_price}")

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price > fair_value:
                    bid_volume = order_depth.buy_orders[bid_price]
                    sell_qty = min(bid_volume, max_sell - sell_volume_used)
                    if sell_qty > 0:
                        orders.append(Order(product, bid_price, -sell_qty))
                        sell_volume_used += sell_qty
                        print(f"  SELL {sell_qty}x at {bid_price}")

            # MAKING LEG
            remaining_buy  = max_buy  - buy_volume_used
            remaining_sell = max_sell - sell_volume_used

            passive_bid_price = best_bid + 1
            if passive_bid_price >= fair_value:
                passive_bid_price = int(fair_value) - 1

            passive_ask_price = best_ask - 1
            if passive_ask_price <= fair_value:
                passive_ask_price = int(fair_value) + 1

            if remaining_buy > 0 and passive_bid_price < best_ask:
                qty = min(remaining_buy, passive_quote_cap)
                if qty > 0:
                    orders.append(Order(product, passive_bid_price, qty))
                    print(f"  PASSIVE BID {qty}x at {passive_bid_price}")

            if remaining_sell > 0 and passive_ask_price > best_bid:
                qty = min(remaining_sell, passive_quote_cap)
                if qty > 0:
                    orders.append(Order(product, passive_ask_price, -qty))
                    print(f"  PASSIVE ASK {qty}x at {passive_ask_price}")

            result[product] = orders

        traderData = json.dumps(data)
        return result, 0, traderData