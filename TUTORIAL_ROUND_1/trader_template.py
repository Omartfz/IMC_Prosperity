"""
=============================================================================
  IMC PROSPERITY 4 — TRADER TEMPLATE
=============================================================================
  Architecture modulaire inspirée des Frankfurt Hedgehogs (2e mondial P3).
  
  STRUCTURE:
  ----------
  1. Trader           → Point d'entrée principal, orchestre tous les ProductTraders
  2. ProductTrader    → Classe de base avec utilitaires communs (orderbook, positions, ordres)
  3. <Stratégie>Trader → Une sous-classe par produit/groupe de produits
  
  COMMENT AJOUTER UN NOUVEAU PRODUIT:
  ------------------------------------
  1. Créer une nouvelle classe héritant de ProductTrader
  2. Implémenter get_orders() avec votre logique de trading
  3. Enregistrer la classe dans PRODUCT_TRADERS du Trader principal
  
  PERSISTENCE D'ÉTAT:
  -------------------
  - AWS Lambda = stateless → rien ne survit entre les appels
  - Utiliser traderData (JSON string, max 50k chars) pour persister
  - self.td_load(key, default) et self.td_save(key, value) simplifient l'accès
  
  RÈGLE D'OR DES POSITION LIMITS:
  --------------------------------
  Si la somme de vos ordres BUY (ou SELL) dépasse la limite, TOUS vos ordres
  sur ce produit sont rejetés. Toujours vérifier remaining capacity avant d'ordonner.
=============================================================================
"""

from datamodel import OrderDepth, TradingState, Order, Trade, Observation
import json
import math
import numpy as np
from typing import Dict, List, Optional, Tuple


# =============================================================================
#  CONFIGURATION — Modifier ici quand de nouveaux produits apparaissent
# =============================================================================

# Position limits par produit (à mettre à jour chaque round)
POS_LIMITS: Dict[str, int] = {
    # Round Tutorial / Round 1 — exemples typiques
    # 'PRODUCT_A': 50,
    # 'PRODUCT_B': 50,
}

# Limite de conversion (pour les produits avec import/export)
CONVERSION_LIMIT = 10

# Directions pour les signaux de trader informé
LONG, NEUTRAL, SHORT = 1, 0, -1

# Nom du trader informé (si applicable — à découvrir pendant la compétition)
INFORMED_TRADER_ID = None  # ex: 'Olivia' en Prosperity 3


# =============================================================================
#  CLASSE DE BASE — ProductTrader
# =============================================================================

class ProductTrader:
    """
    Classe de base pour le trading d'un produit individuel.
    
    Fournit automatiquement:
    - Parsing de l'orderbook (bids/asks triés)
    - Calcul du wall mid (meilleure estimation du prix juste)
    - Gestion des volumes max autorisés (respect des position limits)
    - Méthodes bid() / ask() sécurisées
    - Système de logging structuré
    - Accès simplifié au traderData (persistance entre itérations)
    
    Pour créer un trader pour un nouveau produit:
        class MonProduitTrader(ProductTrader):
            def get_orders(self):
                # Votre logique ici
                # Utiliser self.bid(price, volume) et self.ask(price, volume)
                return {self.name: self.orders}
    """

    def __init__(self, name: str, state: TradingState, 
                 logs: dict, new_trader_data: dict, 
                 product_group: Optional[str] = None):
        
        self.name = name
        self.state = state
        self.logs = logs
        self.new_trader_data = new_trader_data
        self.product_group = product_group or name
        
        # Ordres à soumettre ce tour
        self.orders: List[Order] = []
        
        # Conversions (pour produits avec import/export)
        self.conversions: int = 0
        
        # État précédent (traderData désérialisé)
        self._last_trader_data = self._parse_trader_data()
        
        # Position limits et position actuelle
        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.position = state.position.get(self.name, 0)
        
        # Position attendue (mettre à jour si on anticipe des fills)
        self.expected_position = self.position
        
        # Orderbook parsé
        self.bids, self.asks = self._parse_orderbook()
        
        # Prix clés
        self.best_bid, self.best_ask = self._get_best_prices()
        self.bid_wall, self.ask_wall = self._get_walls()
        self.wall_mid = self._get_wall_mid()
        self.mid = self._get_mid()
        
        # Volumes
        self.max_buy_vol, self.max_sell_vol = self._get_max_volumes()
        self.total_bid_vol, self.total_ask_vol = self._get_total_volumes()

    # -------------------------------------------------------------------------
    #  ORDERBOOK PARSING
    # -------------------------------------------------------------------------
    
    def _parse_orderbook(self) -> Tuple[Dict[int, int], Dict[int, int]]:
        """Parse l'orderbook en bids et asks avec volumes positifs, triés."""
        bids, asks = {}, {}
        
        depth = self.state.order_depths.get(self.name)
        if depth is None:
            return bids, asks
            
        # Bids: prix décroissant, volumes positifs
        if depth.buy_orders:
            bids = {p: abs(v) for p, v in 
                    sorted(depth.buy_orders.items(), reverse=True)}
        
        # Asks: prix croissant, volumes positifs  
        if depth.sell_orders:
            asks = {p: abs(v) for p, v in 
                    sorted(depth.sell_orders.items())}
        
        return bids, asks

    def _get_best_prices(self) -> Tuple[Optional[int], Optional[int]]:
        """Retourne le meilleur bid et le meilleur ask."""
        best_bid = max(self.bids.keys()) if self.bids else None
        best_ask = min(self.asks.keys()) if self.asks else None
        return best_bid, best_ask

    def _get_walls(self) -> Tuple[Optional[int], Optional[int]]:
        """
        Retourne les 'murs' de l'orderbook — les niveaux de prix les plus 
        profonds (plus éloignés du mid). Ces murs correspondent souvent aux 
        quotes de market makers qui connaissent le vrai prix.
        """
        bid_wall = min(self.bids.keys()) if self.bids else None
        ask_wall = max(self.asks.keys()) if self.asks else None
        return bid_wall, ask_wall

    def _get_wall_mid(self) -> Optional[float]:
        """
        Wall Mid = moyenne entre bid wall et ask wall.
        C'est souvent la meilleure estimation du 'vrai prix' en Prosperity,
        car les market makers deep-book quotent autour du fair value.
        """
        if self.bid_wall is not None and self.ask_wall is not None:
            return (self.bid_wall + self.ask_wall) / 2
        return None

    def _get_mid(self) -> Optional[float]:
        """Mid price classique = (best_bid + best_ask) / 2."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return None

    # -------------------------------------------------------------------------
    #  VOLUMES & POSITION MANAGEMENT
    # -------------------------------------------------------------------------

    def _get_max_volumes(self) -> Tuple[int, int]:
        """
        Calcule le volume max achetable/vendable sans dépasser la position limit.
        CRUCIAL: si vous envoyez des ordres dont le volume total dépasse la 
        limite, TOUS vos ordres sont annulés.
        """
        max_buy = self.position_limit - self.position
        max_sell = self.position_limit + self.position
        return max_buy, max_sell

    def _get_total_volumes(self) -> Tuple[int, int]:
        """Volume total disponible dans le book côté bid et ask."""
        total_bid = sum(self.bids.values()) if self.bids else 0
        total_ask = sum(self.asks.values()) if self.asks else 0
        return total_bid, total_ask

    # -------------------------------------------------------------------------
    #  ORDER SUBMISSION
    # -------------------------------------------------------------------------

    def bid(self, price: int, volume: int, log: bool = True) -> int:
        """
        Place un ordre d'achat (BUY).
        Clamp automatiquement le volume au max autorisé.
        Retourne le volume effectivement placé.
        """
        actual_vol = min(abs(int(volume)), self.max_buy_vol)
        if actual_vol <= 0:
            return 0
            
        order = Order(self.name, int(price), actual_vol)
        self.orders.append(order)
        self.max_buy_vol -= actual_vol
        
        if log:
            self.log("BUY_ORDER", {"price": int(price), "vol": actual_vol})
        
        return actual_vol

    def ask(self, price: int, volume: int, log: bool = True) -> int:
        """
        Place un ordre de vente (SELL).
        Clamp automatiquement le volume au max autorisé.
        Retourne le volume effectivement placé.
        """
        actual_vol = min(abs(int(volume)), self.max_sell_vol)
        if actual_vol <= 0:
            return 0
            
        order = Order(self.name, int(price), -actual_vol)
        self.orders.append(order)
        self.max_sell_vol -= actual_vol
        
        if log:
            self.log("SELL_ORDER", {"price": int(price), "vol": actual_vol})
        
        return actual_vol

    # -------------------------------------------------------------------------
    #  TAKING — Prendre la liquidité existante
    # -------------------------------------------------------------------------

    def take_asks_below(self, threshold: float, max_vol: Optional[int] = None):
        """
        Achète tout ce qui est proposé en dessous du seuil.
        Utile pour: market making (prendre les bonnes affaires), arbitrage.
        """
        remaining = max_vol if max_vol else self.max_buy_vol
        for price, vol in self.asks.items():
            if price < threshold and remaining > 0:
                taken = self.bid(price, min(vol, remaining), log=False)
                remaining -= taken
            else:
                break

    def take_bids_above(self, threshold: float, max_vol: Optional[int] = None):
        """
        Vend tout ce qui est demandé au-dessus du seuil.
        Symétrique de take_asks_below.
        """
        remaining = max_vol if max_vol else self.max_sell_vol
        for price, vol in self.bids.items():
            if price > threshold and remaining > 0:
                taken = self.ask(price, min(vol, remaining), log=False)
                remaining -= taken
            else:
                break

    # -------------------------------------------------------------------------
    #  PERSISTENCE — TraderData (état entre les itérations)
    # -------------------------------------------------------------------------

    def _parse_trader_data(self) -> dict:
        """Parse le traderData JSON du state."""
        try:
            if self.state.traderData and self.state.traderData != '':
                return json.loads(self.state.traderData)
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    def td_load(self, key: str, default=None):
        """Charge une valeur depuis le traderData précédent."""
        return self._last_trader_data.get(key, default)

    def td_save(self, key: str, value):
        """Sauvegarde une valeur dans le nouveau traderData."""
        self.new_trader_data[key] = value

    # -------------------------------------------------------------------------
    #  EMA — Exponential Moving Average (utilitaire courant)
    # -------------------------------------------------------------------------

    def update_ema(self, key: str, value: float, window: int) -> float:
        """
        Met à jour une EMA stockée dans traderData.
        Formule: EMA_new = alpha * value + (1 - alpha) * EMA_old
        avec alpha = 2 / (window + 1)
        """
        old_ema = self.td_load(key, value)  # init à value si premier appel
        alpha = 2 / (window + 1)
        new_ema = alpha * value + (1 - alpha) * old_ema
        self.td_save(key, new_ema)
        return new_ema

    # -------------------------------------------------------------------------
    #  INFORMED TRADER DETECTION
    # -------------------------------------------------------------------------

    def check_for_informed(self) -> Tuple[int, Optional[int], Optional[int]]:
        """
        Détecte les trades du trader informé (ex: 'Olivia' en P3).
        Retourne (direction, dernier_achat_ts, dernière_vente_ts).
        
        Patterns typiques en Prosperity:
        - Le trader informé achète au daily min et vend au daily max
        - Son identification permet d'anticiper les mouvements
        """
        if INFORMED_TRADER_ID is None:
            return NEUTRAL, None, None
            
        # Charger l'état précédent
        bought_ts, sold_ts = self.td_load(f'{self.name}_informed', [None, None])
        
        # Scanner les trades de cette itération
        all_trades = (self.state.market_trades.get(self.name, []) + 
                      self.state.own_trades.get(self.name, []))
        
        for trade in all_trades:
            if trade.buyer == INFORMED_TRADER_ID:
                bought_ts = trade.timestamp
            if trade.seller == INFORMED_TRADER_ID:
                sold_ts = trade.timestamp
        
        # Sauvegarder l'état
        self.td_save(f'{self.name}_informed', [bought_ts, sold_ts])
        
        # Déterminer la direction
        direction = NEUTRAL
        if bought_ts and not sold_ts:
            direction = LONG
        elif sold_ts and not bought_ts:
            direction = SHORT
        elif bought_ts and sold_ts:
            if sold_ts > bought_ts:
                direction = SHORT
            elif bought_ts > sold_ts:
                direction = LONG
        
        self.log('INFORMED', {'dir': direction, 'buy_ts': bought_ts, 'sell_ts': sold_ts})
        return direction, bought_ts, sold_ts

    # -------------------------------------------------------------------------
    #  LOGGING
    # -------------------------------------------------------------------------

    def log(self, key: str, value):
        """
        Log structuré — sera affiché dans les logs de debug.
        Groupé par product_group pour une lecture facile dans le dashboard.
        """
        group = self.logs.setdefault(self.product_group, {})
        group[key] = value

    # -------------------------------------------------------------------------
    #  INTERFACE — À surcharger
    # -------------------------------------------------------------------------

    def get_orders(self) -> Dict[str, List[Order]]:
        """
        SURCHARGER CETTE MÉTHODE dans chaque sous-classe.
        Doit retourner {product_name: [list of Orders]}
        """
        raise NotImplementedError("Implémenter get_orders() dans la sous-classe")


# =============================================================================
#  EXEMPLES DE TRADERS — À adapter pour Prosperity 4
# =============================================================================

class StaticPriceTrader(ProductTrader):
    """
    Trader pour un produit à prix fixe (ex: Rainforest Resin en P3, ~10000).
    
    Stratégie:
    1. Prendre toute liquidité avec edge positif par rapport au fair price
    2. Poster des ordres passifs en overbidding/undercutting
    3. Aplatir la position si trop skewée
    """

    FAIR_PRICE = 10_000  # À ajuster selon le produit

    def get_orders(self) -> Dict[str, List[Order]]:
        if self.wall_mid is None:
            return {self.name: self.orders}

        fair = self.FAIR_PRICE

        # 1. TAKING — prendre les bonnes affaires
        self.take_asks_below(fair)       # acheter sous le fair
        self.take_bids_above(fair)       # vendre au-dessus du fair

        # Aplatir la position au fair price si inventaire skewé
        if self.position > 0:
            self.take_bids_above(fair, max_vol=self.position)
        elif self.position < 0:
            self.take_asks_below(fair + 1, max_vol=abs(self.position))

        # 2. MAKING — poster des ordres passifs
        bid_price = int(self.bid_wall + 1) if self.bid_wall else int(fair - 2)
        ask_price = int(self.ask_wall - 1) if self.ask_wall else int(fair + 2)

        # Overbidding: améliorer le meilleur bid existant (si encore sous le mid)
        if self.best_bid and self.best_bid + 1 < fair:
            bid_price = max(bid_price, self.best_bid + 1)
        
        # Undercutting: améliorer le meilleur ask existant (si encore au-dessus du mid)
        if self.best_ask and self.best_ask - 1 > fair:
            ask_price = min(ask_price, self.best_ask - 1)

        self.bid(bid_price, self.max_buy_vol)
        self.ask(ask_price, self.max_sell_vol)

        return {self.name: self.orders}


class RandomWalkTrader(ProductTrader):
    """
    Trader pour un produit en random walk lent (ex: Kelp en P3).
    
    Même logique que StaticPriceTrader mais le fair price = wall_mid courant.
    Le prix bouge peu entre les itérations, donc on quote autour du mid.
    """

    def get_orders(self) -> Dict[str, List[Order]]:
        if self.wall_mid is None:
            return {self.name: self.orders}

        fair = self.wall_mid

        # 1. TAKING
        self.take_asks_below(fair)
        self.take_bids_above(fair)

        # Aplatir au fair si position trop grande
        if self.position > 0:
            self.take_bids_above(fair, max_vol=self.position)
        elif self.position < 0:
            self.take_asks_below(fair + 1, max_vol=abs(self.position))

        # 2. MAKING — overbid/undercut autour du wall mid
        bid_price = int(self.bid_wall + 1) if self.bid_wall else int(fair - 1)
        ask_price = int(self.ask_wall - 1) if self.ask_wall else int(fair + 1)

        # Ajuster pour rester du bon côté du mid
        if bid_price >= fair:
            bid_price = int(fair - 1)
        if ask_price <= fair:
            ask_price = int(fair + 1)

        self.bid(bid_price, self.max_buy_vol)
        self.ask(ask_price, self.max_sell_vol)

        return {self.name: self.orders}


class SpreadTrader(ProductTrader):
    """
    Template pour trading de spread/ETF arbitrage.
    
    Stratégie:
    - Calculer spread = prix_basket - somme(prix_constituants * poids)
    - Acheter le basket quand spread < -threshold (trop cheap)
    - Vendre le basket quand spread > +threshold (trop cher)
    - Fermer quand le spread revient à 0
    
    À personnaliser avec les bons constituants et seuils.
    """
    
    CONSTITUENTS: List[str] = []      # ex: ['PRODUCT_A', 'PRODUCT_B']
    WEIGHTS: List[float] = []          # ex: [6, 3, 1]
    THRESHOLD: float = 50             # seuil d'entrée
    PREMIUM: float = 0                # premium moyen du basket

    def calculate_spread(self) -> Optional[float]:
        """Calcule le spread basket - index synthétique."""
        if self.wall_mid is None:
            return None
            
        try:
            constituent_mids = []
            for symbol in self.CONSTITUENTS:
                depth = self.state.order_depths.get(symbol)
                if not depth or not depth.buy_orders or not depth.sell_orders:
                    return None
                bid_wall = min(depth.buy_orders.keys())
                ask_wall = max(depth.sell_orders.keys())
                constituent_mids.append((bid_wall + ask_wall) / 2)
            
            index_price = sum(m * w for m, w in zip(constituent_mids, self.WEIGHTS))
            return self.wall_mid - index_price - self.PREMIUM
        except:
            return None

    def get_orders(self) -> Dict[str, List[Order]]:
        spread = self.calculate_spread()
        if spread is None:
            return {self.name: self.orders}

        self.log('SPREAD', round(spread, 2))

        # Ouvrir des positions si spread dépasse le seuil
        if spread > self.THRESHOLD and self.max_sell_vol > 0:
            # Basket trop cher → vendre
            self.ask(self.best_bid or self.bid_wall, self.max_sell_vol)

        elif spread < -self.THRESHOLD and self.max_buy_vol > 0:
            # Basket trop cheap → acheter
            self.bid(self.best_ask or self.ask_wall, self.max_buy_vol)

        # Fermer les positions quand spread revient vers 0
        elif spread > 0 and self.position > 0:
            self.ask(self.best_bid or self.bid_wall, self.position)

        elif spread < 0 and self.position < 0:
            self.bid(self.best_ask or self.ask_wall, abs(self.position))

        return {self.name: self.orders}


# =============================================================================
#  TRADER PRINCIPAL — Point d'entrée
# =============================================================================

class Trader:
    """
    Point d'entrée principal appelé par la simulation Prosperity.
    
    La méthode run() est appelée à chaque itération avec le TradingState.
    Elle doit retourner: (orders_dict, conversions, traderData_string)
    """

    # =========================================================================
    #  ENREGISTREMENT DES TRADERS PAR PRODUIT
    # =========================================================================
    #  
    #  Modifier ce dictionnaire quand de nouveaux produits apparaissent.
    #  Clé = nom du produit (trigger), Valeur = classe du trader.
    #  
    #  IMPORTANT: la clé doit correspondre à un produit présent dans 
    #  state.order_depths pour que le trader soit activé.
    #
    #  Exemple:
    #  PRODUCT_TRADERS = {
    #      'RAINFOREST_RESIN': StaticPriceTrader,
    #      'KELP': RandomWalkTrader,
    #      'PICNIC_BASKET1': BasketTrader,
    #  }
    # =========================================================================
    
    PRODUCT_TRADERS: Dict[str, type] = {
        # Décommenter et adapter quand les produits sont connus:
        # 'PRODUCT_A': StaticPriceTrader,
        # 'PRODUCT_B': RandomWalkTrader,
    }

    def bid(self):
        """Requis pour le Round 2 Algo (enchère). Ignoré les autres rounds."""
        return 15  # À ajuster selon le round

    def run(self, state: TradingState):
        """
        Méthode principale appelée à chaque itération.
        
        Returns:
            result: Dict[str, List[Order]] — ordres par produit
            conversions: int — requête de conversion (0 si non applicable)
            traderData: str — état sérialisé pour la prochaine itération
        """
        
        # État partagé entre tous les traders
        new_trader_data: dict = {}
        logs: dict = {
            "_META": {
                "ts": state.timestamp,
                "pos": dict(state.position) if state.position else {},
            }
        }
        
        # Exécuter chaque trader de produit
        result: Dict[str, List[Order]] = {}
        conversions: int = 0
        
        for trigger_symbol, trader_class in self.PRODUCT_TRADERS.items():
            if trigger_symbol not in state.order_depths:
                continue
                
            try:
                trader = trader_class(
                    name=trigger_symbol,
                    state=state,
                    logs=logs,
                    new_trader_data=new_trader_data,
                )
                orders = trader.get_orders()
                result.update(orders)
                
                # Récupérer les conversions si le trader en a
                if hasattr(trader, 'conversions') and trader.conversions != 0:
                    conversions = trader.conversions
                    
            except Exception as e:
                logs[f"ERROR_{trigger_symbol}"] = str(e)
        
        # Sérialiser l'état et les logs
        try:
            trader_data_str = json.dumps(new_trader_data)
        except:
            trader_data_str = ''
        
        # Print les logs (visibles dans les fichiers de debug)
        try:
            print(json.dumps(logs, default=str))
        except:
            pass
        
        return result, conversions, trader_data_str