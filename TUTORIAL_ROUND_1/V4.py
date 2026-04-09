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
        "TOMATOES": 0.10,
    }

    PASSIVE_CAPS = {
        "EMERALDS": 15,
        "TOMATOES": 8
    }

    SKEW_TICKS = {
        "EMERALDS": 1,
        "TOMATOES": 2,  # more aggressive skew for volatile asset
    }

    TAKER_MIN_EDGE = {
        "EMERALDS": 0.5,
        "TOMATOES": 1.0,  # require bigger edge on volatile asset
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
        bid_wall = max(order_depth.buy_orders, key=lambda p: order_depth.buy_orders[p])
        ask_wall = min(order_depth.sell_orders, key=lambda p: abs(order_depth.sell_orders[p]))
        wall_mid = (bid_wall + ask_wall) / 2.0

        if product == "EMERALDS":
            bid_wall = min(order_depth.buy_orders.keys())
            ask_wall = max(order_depth.sell_orders.keys())
            return (bid_wall + ask_wall) / 2.0

        if product == "TOMATOES":
            bid_prices = order_depth.buy_orders    # {price: volume}
            ask_prices = order_depth.sell_orders   # {price: -volume}

            total_bid_vol = sum(bid_prices.values())
            total_ask_vol = sum(abs(v) for v in ask_prices.values())

            bid_vwap = sum(p * v for p, v in bid_prices.items()) / total_bid_vol
            ask_vwap = sum(p * abs(v) for p, v in ask_prices.items()) / total_ask_vol

            vwap_mid = (bid_vwap + ask_vwap) / 2.0
            return self._update_ema(data, product, vwap_mid)  # smooth it slightly

        # Default: wall mid (original behavior)
        return wall_mid

    def run(self, state: TradingState):
        data = self._safe_load_data(state.traderData)
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
            skew = position / limit

            # TAKING LEG
            inventory_ratio = abs(position) / limit  # 0 = flat, 1 = at limit
            base_edge = self.TAKER_MIN_EDGE.get(product, 0.5)

            for ask_price in sorted(order_depth.sell_orders.keys()):
                edge = fair_value - ask_price
                # Require bigger edge when already long (extending position)
                # Require smaller edge when short (reduces position)
                direction_penalty = 1.0 + (skew * inventory_ratio)
                min_edge = base_edge * direction_penalty
                if edge > min_edge:
                    ask_volume = abs(order_depth.sell_orders[ask_price])
                    buy_qty = min(ask_volume, max_buy - buy_volume_used)
                    if buy_qty > 0:
                        orders.append(Order(product, ask_price, buy_qty))
                        buy_volume_used += buy_qty
                        print(f"  BUY  {buy_qty}x at {ask_price}")

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                edge = bid_price - fair_value
                direction_penalty = max(0.0, 1.0 - (skew * inventory_ratio))
                min_edge = base_edge * direction_penalty
                if edge > min_edge:
                    bid_volume = order_depth.buy_orders[bid_price]
                    sell_qty = min(bid_volume, max_sell - sell_volume_used)
                    if sell_qty > 0:
                        orders.append(Order(product, bid_price, -sell_qty))
                        sell_volume_used += sell_qty
                        print(f"  SELL {sell_qty}x at {bid_price}")

            # MAKING LEG
            buy_room  = (max_buy  - buy_volume_used) / limit
            sell_room = (max_sell - sell_volume_used) / limit
            cap = self.PASSIVE_CAPS.get(product, 10)
            skew_ticks = self.SKEW_TICKS.get(product, 1)

            passive_bid_price = best_bid + 1
            if passive_bid_price >= fair_value:
                passive_bid_price = int(fair_value) - 1

            passive_ask_price = best_ask - 1
            if passive_ask_price <= fair_value:
                passive_ask_price = int(fair_value) + 1

            passive_bid_price -= int(skew * skew_ticks)
            passive_ask_price -= int(skew * skew_ticks)

            if buy_room > 0 and passive_bid_price < best_ask:
                qty = max(0, int(cap * (1 - skew) * buy_room))
                if qty > 0:
                    orders.append(Order(product, passive_bid_price, qty))
                    print(f"  PASSIVE BID {qty}x at {passive_bid_price}")

            if sell_room > 0 and passive_ask_price > best_bid:
                qty = max(0, int(cap * (1 + skew) * sell_room))
                if qty > 0:
                    orders.append(Order(product, passive_ask_price, -qty))
                    print(f"  PASSIVE ASK {qty}x at {passive_ask_price}")

            result[product] = orders

        traderData = json.dumps(data)
        return result, 0, traderData