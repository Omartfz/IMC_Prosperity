# =============================================================================
#  PREMIER ALGO PROSPERITY 4
# =============================================================================
#  Stratégie : Market Making simple avec Wall Mid
#
#  Pour chaque produit :
#    1. Calculer le fair value (wall mid)
#    2. TAKING : acheter tout ce qui est en vente SOUS le fair value
#    3. TAKING : vendre tout ce qui est demandé AU-DESSUS du fair value
#    4. MAKING : poster un bid juste en dessous du fair value
#    5. MAKING : poster un ask juste au-dessus du fair value
#
#  Cet algo est volontairement simple et très commenté.
#  Il fonctionnera pour n'importe quel produit sans modification.
# =============================================================================

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:

    # =========================================================================
    #  POSITION LIMITS — À mettre à jour quand les produits sont annoncés
    # =========================================================================
    #  Quand le Round 1 commence, tu verras les noms des produits et leurs
    #  limits dans le wiki/A.R.I.A. Uplink. Ajoute-les ici.
    #
    #  Par défaut on met 50, qui est une limite courante dans Prosperity.
    #  Si un produit a une limite différente, change-la ici.
    # =========================================================================

    POSITION_LIMITS = {
        "EMERALDS": 80,    # Prix fixe ~10000, spread ~16
        "TOMATOES": 80,    # Random walk ~5000, spread ~13
    }

    # Si un produit n'est pas dans le dict, on utilise cette valeur
    DEFAULT_LIMIT = 50

    # Pour EMERALDS, on connaît le prix exact — on peut hard-coder
    FIXED_FAIR_VALUES = {
        "EMERALDS": 10_000,
    }

    def bid(self):
        """Requis pour le Round 2 Algo. Ignoré les autres rounds."""
        return 15

    def run(self, state: TradingState):
        """
        Méthode appelée à chaque itération (jusqu'à 10 000 fois).
        
        Reçoit : state (TradingState) — l'état complet du marché
        Retourne : (result, conversions, traderData)
        """
        # Dictionnaire qui contiendra nos ordres pour chaque produit
        result: Dict[str, List[Order]] = {}

        # Pour le debug — sera visible dans les logs
        log_data = {}

        # =================================================================
        #  BOUCLE SUR CHAQUE PRODUIT DISPONIBLE
        # =================================================================
        for product in state.order_depths:

            # Récupérer l'order book de ce produit
            order_depth: OrderDepth = state.order_depths[product]

            # Liste des ordres qu'on va envoyer pour ce produit
            orders: List[Order] = []

            # ---------------------------------------------------------
            #  ÉTAPE 0 : Vérifier que le book n'est pas vide
            # ---------------------------------------------------------
            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            # ---------------------------------------------------------
            #  ÉTAPE 1 : Calculer le FAIR VALUE
            # ---------------------------------------------------------
            # Pour les produits à prix fixe (EMERALDS) : on utilise le
            # prix connu directement — c'est plus fiable.
            # Pour les autres (TOMATOES) : on utilise le wall mid.

            bid_wall = min(order_depth.buy_orders.keys())
            ask_wall = max(order_depth.sell_orders.keys())
            wall_mid = (bid_wall + ask_wall) / 2

            # Utiliser le prix fixe si connu, sinon le wall mid
            fair_value = self.FIXED_FAIR_VALUES.get(product, wall_mid)

            # Best bid et best ask (les prix les plus proches du centre)
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())

            # ---------------------------------------------------------
            #  ÉTAPE 2 : Calculer les VOLUMES MAX (position limits)
            # ---------------------------------------------------------
            # Position actuelle dans ce produit
            position = state.position.get(product, 0)

            # Limite de position pour ce produit
            limit = self.POSITION_LIMITS.get(product, self.DEFAULT_LIMIT)

            # Volume max qu'on peut encore acheter sans dépasser la limite
            max_buy = limit - position

            # Volume max qu'on peut encore vendre sans dépasser la limite
            max_sell = limit + position

            # Compteurs pour tracker combien on a déjà utilisé
            buy_volume_used = 0
            sell_volume_used = 0

            # ---------------------------------------------------------
            #  ÉTAPE 3 : TAKING — Acheter tout ce qui est SOUS le fair
            # ---------------------------------------------------------
            # On parcourt les sell_orders (les asks) du moins cher au
            # plus cher. Si le prix est sous notre fair value, on achète.
            #
            # Rappel : sell_orders a des quantités NÉGATIVES !

            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price < fair_value:
                    # Volume disponible à ce prix (abs car négatif)
                    ask_volume = abs(order_depth.sell_orders[ask_price])

                    # Ne pas dépasser notre max
                    can_buy = max_buy - buy_volume_used
                    buy_qty = min(ask_volume, can_buy)

                    if buy_qty > 0:
                        # Order(produit, prix, quantité POSITIVE = BUY)
                        orders.append(Order(product, ask_price, buy_qty))
                        buy_volume_used += buy_qty

            # ---------------------------------------------------------
            #  ÉTAPE 4 : TAKING — Vendre tout ce qui est AU-DESSUS du fair
            # ---------------------------------------------------------
            # On parcourt les buy_orders (les bids) du plus cher au
            # moins cher. Si le prix est au-dessus de notre fair value,
            # on vend.

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price > fair_value:
                    # Volume demandé à ce prix
                    bid_volume = order_depth.buy_orders[bid_price]

                    # Ne pas dépasser notre max
                    can_sell = max_sell - sell_volume_used
                    sell_qty = min(bid_volume, can_sell)

                    if sell_qty > 0:
                        # Order(produit, prix, quantité NÉGATIVE = SELL)
                        orders.append(Order(product, bid_price, -sell_qty))
                        sell_volume_used += sell_qty

            # ---------------------------------------------------------
            #  ÉTAPE 5 : MAKING — Poster des ordres passifs
            # ---------------------------------------------------------
            # Après avoir pris les bonnes affaires, on poste des ordres
            # qui restent dans le book en attendant que les bots viennent.
            #
            # On overbid (améliore le meilleur bid) et on undercut
            # (améliore le meilleur ask) pour être servi en priorité.

            # --- BID PASSIF (ordre d'achat en attente) ---
            # On place notre bid 1 au-dessus du best bid actuel,
            # mais jamais au-dessus du fair value (sinon on surpaie)
            passive_bid_price = best_bid + 1
            if passive_bid_price >= fair_value:
                passive_bid_price = int(fair_value) - 1

            remaining_buy = max_buy - buy_volume_used
            if remaining_buy > 0:
                orders.append(Order(product, passive_bid_price, remaining_buy))

            # --- ASK PASSIF (ordre de vente en attente) ---
            # On place notre ask 1 en dessous du best ask actuel,
            # mais jamais en dessous du fair value (sinon on brade)
            passive_ask_price = best_ask - 1
            if passive_ask_price <= fair_value:
                passive_ask_price = int(fair_value) + 1

            remaining_sell = max_sell - sell_volume_used
            if remaining_sell > 0:
                orders.append(Order(product, passive_ask_price, -remaining_sell))

            # Sauvegarder les ordres pour ce produit
            result[product] = orders

            # ---------------------------------------------------------
            #  LOGGING — Pour débugger dans les logs Prosperity
            # ---------------------------------------------------------
            log_data[product] = {
                "fair": round(fair_value, 1),
                "bid_wall": bid_wall,
                "ask_wall": ask_wall,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "pos": position,
                "max_buy": max_buy,
                "max_sell": max_sell,
                "n_orders": len(orders),
            }

        # Afficher les logs (visibles dans le fichier de debug)
        print(json.dumps(log_data))

        # Pas de conversions pour l'instant, pas de state à persister
        traderData = ""
        conversions = 0

        return result, conversions, traderData
