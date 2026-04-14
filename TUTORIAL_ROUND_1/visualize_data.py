"""
=============================================================================
  PROSPERITY 4 — Visualisation des données du Tutorial Round
=============================================================================
  
  Usage :
    python visualize_data.py
  
  Prérequis :
    pip install pandas matplotlib
  
  Place ce script dans le même dossier que les 4 fichiers CSV :
    - prices_round_0_day_-1.csv
    - prices_round_0_day_-2.csv
    - trades_round_0_day_-1.csv
    - trades_round_0_day_-2.csv
=============================================================================
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os

# =============================================================================
#  1. CHARGEMENT DES DONNÉES
# =============================================================================

# Adapter ce chemin si nécessaire
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Round1_data")

def load_data(data_dir=DATA_DIR):
    """Charge et concatène les fichiers prices et trades des 2 jours."""

    prices_files = [
        os.path.join(data_dir, "prices_round_1_day_-2.csv"),
        os.path.join(data_dir, "prices_round_1_day_-1.csv"),
        os.path.join(data_dir, "prices_round_1_day_0.csv"),
    ]
    trades_files = [
        os.path.join(data_dir, "trades_round_1_day_-2.csv"),
        os.path.join(data_dir, "trades_round_1_day_-1.csv"),
        os.path.join(data_dir, "trades_round_1_day_0.csv"),
    ]

    prices_list, trades_list = [], []

    for f in prices_files:
        if os.path.exists(f):
            df = pd.read_csv(f, sep=";")
            prices_list.append(df)
            print(f"  Chargé: {f} ({len(df)} lignes)")

    for f in trades_files:
        if os.path.exists(f):
            df = pd.read_csv(f, sep=";")
            trades_list.append(df)
            print(f"  Chargé: {f} ({len(df)} lignes)")

    prices = pd.concat(prices_list, ignore_index=True) if prices_list else pd.DataFrame()
    trades = pd.concat(trades_list, ignore_index=True) if trades_list else pd.DataFrame()

    return prices, trades


# =============================================================================
#  2. STATISTIQUES RÉSUMÉES
# =============================================================================

def print_summary(prices, trades):
    """Affiche un résumé des produits, prix, spreads et volumes."""

    print("\n" + "=" * 60)
    print("  RÉSUMÉ DES PRODUITS")
    print("=" * 60)

    for product in sorted(prices["product"].unique()):
        pp = prices[prices["product"] == product]
        tt = trades[trades["symbol"] == product] if "symbol" in trades.columns else pd.DataFrame()

        mid = pp["mid_price"]
        spread = pp["ask_price_1"] - pp["bid_price_1"]

        # Wall mid
        wall_mid = (pp["bid_price_2"] + pp["ask_price_2"]) / 2

        print(f"\n  📦 {product}")
        print(f"     Mid price    : mean={mid.mean():.1f}  std={mid.std():.1f}  min={mid.min():.1f}  max={mid.max():.1f}")
        print(f"     Wall mid     : mean={wall_mid.mean():.1f}  std={wall_mid.std():.1f}")
        print(f"     Spread (L1)  : mean={spread.mean():.1f}  min={spread.min():.0f}  max={spread.max():.0f}")
        print(f"     Volume bid_1 : mean={pp['bid_volume_1'].mean():.1f}")
        print(f"     Volume ask_1 : mean={pp['ask_volume_1'].mean():.1f}")
        print(f"     Nb trades    : {len(tt)}")

        if len(tt) > 0:
            print(f"     Trade prix   : mean={tt['price'].mean():.1f}  min={tt['price'].min():.0f}  max={tt['price'].max():.0f}")
            print(f"     Trade qty    : mean={tt['quantity'].mean():.1f}")

        # Détection du type de produit
        if mid.std() < 5:
            print(f"     → TYPE : Prix fixe (~{mid.mean():.0f})")
        else:
            print(f"     → TYPE : Random walk (std={mid.std():.1f})")


# =============================================================================
#  3. GRAPHIQUES
# =============================================================================

def plot_orderbook(prices, trades, product, day=None, ax=None):
    """
    Graphique principal : orderbook + trades pour un produit.
    
    Affiche :
    - Best bid / best ask (lignes continues)
    - Bid wall / ask wall (lignes pointillées)
    - Wall mid (ligne violette)
    - Trades (points orange)
    """
    pp = prices[prices["product"] == product].copy()
    tt = trades[trades["symbol"] == product].copy() if "symbol" in trades.columns else pd.DataFrame()

    if day is not None:
        pp = pp[pp["day"] == day]
        # Trades n'ont pas de colonne day, filtrer par timestamp
        if len(tt) > 0:
            max_ts = pp["timestamp"].max()
            min_ts = pp["timestamp"].min()
            tt = tt[(tt["timestamp"] >= min_ts) & (tt["timestamp"] <= max_ts)]

    pp = pp.sort_values("timestamp")

    if ax is None:
        fig, ax = plt.subplots(figsize=(14, 5))

    ts = pp["timestamp"] / 1000  # en milliers pour lisibilité

    # Order book levels
    ax.plot(ts, pp["ask_price_1"], color="#E24B4A", linewidth=0.8, alpha=0.7, label="Best ask")
    ax.plot(ts, pp["bid_price_1"], color="#1D9E75", linewidth=0.8, alpha=0.7, label="Best bid")

    # Walls (level 2)
    ax.plot(ts, pp["ask_price_2"], color="#E24B4A", linewidth=0.5, alpha=0.3, linestyle="--", label="Ask wall")
    ax.plot(ts, pp["bid_price_2"], color="#1D9E75", linewidth=0.5, alpha=0.3, linestyle="--", label="Bid wall")

    # Wall mid
    wall_mid = (pp["bid_price_2"] + pp["ask_price_2"]) / 2
    ax.plot(ts, wall_mid, color="#7F77DD", linewidth=1.5, alpha=0.8, label="Wall mid")

    # Trades
    if len(tt) > 0:
        trade_ts = tt["timestamp"] / 1000
        ax.scatter(trade_ts, tt["price"], color="#EF9F27", s=tt["quantity"] * 5, 
                   alpha=0.6, zorder=5, label="Trades", edgecolors="none")

    day_label = f" (day {day})" if day is not None else ""
    ax.set_title(f"{product}{day_label}", fontsize=14, fontweight="bold")
    ax.set_xlabel("Timestamp (x1000)")
    ax.set_ylabel("Prix")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.15)

    return ax


def plot_spread(prices, product, day=None, ax=None):
    """Graphique du spread (best ask - best bid) dans le temps."""

    pp = prices[prices["product"] == product].copy()
    if day is not None:
        pp = pp[pp["day"] == day]
    pp = pp.sort_values("timestamp")

    if ax is None:
        fig, ax = plt.subplots(figsize=(14, 3))

    ts = pp["timestamp"] / 1000
    spread = pp["ask_price_1"] - pp["bid_price_1"]

    ax.fill_between(ts, spread, color="#7F77DD", alpha=0.3)
    ax.plot(ts, spread, color="#7F77DD", linewidth=0.8)
    ax.axhline(y=spread.mean(), color="#534AB7", linestyle="--", linewidth=0.8, 
               label=f"Moyenne = {spread.mean():.1f}")

    ax.set_title(f"{product} — Spread", fontsize=12)
    ax.set_xlabel("Timestamp (x1000)")
    ax.set_ylabel("Spread")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.15)

    return ax


def plot_volumes(prices, product, day=None, ax=None):
    """Graphique des volumes bid/ask au level 1."""

    pp = prices[prices["product"] == product].copy()
    if day is not None:
        pp = pp[pp["day"] == day]
    pp = pp.sort_values("timestamp")

    if ax is None:
        fig, ax = plt.subplots(figsize=(14, 3))

    ts = pp["timestamp"] / 1000

    ax.bar(ts, pp["bid_volume_1"], width=0.8, color="#1D9E75", alpha=0.4, label="Bid vol")
    ax.bar(ts, -pp["ask_volume_1"], width=0.8, color="#E24B4A", alpha=0.4, label="Ask vol")

    ax.set_title(f"{product} — Volumes L1", fontsize=12)
    ax.set_xlabel("Timestamp (x1000)")
    ax.set_ylabel("Volume (bid +, ask -)")
    ax.legend(fontsize=8)
    ax.axhline(y=0, color="gray", linewidth=0.5)
    ax.grid(True, alpha=0.15)

    return ax


def plot_trade_distribution(trades, product, ax=None):
    """Histogramme des prix de trades."""

    tt = trades[trades["symbol"] == product]
    if len(tt) == 0:
        return

    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 4))

    ax.hist(tt["price"], bins=40, color="#7F77DD", alpha=0.7, edgecolor="white", linewidth=0.5)
    ax.axvline(x=tt["price"].mean(), color="#E24B4A", linestyle="--", linewidth=1, 
               label=f"Moyenne = {tt['price'].mean():.0f}")

    ax.set_title(f"{product} — Distribution des prix de trades", fontsize=12)
    ax.set_xlabel("Prix")
    ax.set_ylabel("Nombre de trades")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.15)

    return ax


def plot_full_dashboard(prices, trades, product, day=-1):
    """
    Dashboard complet pour un produit :
    - Orderbook + trades
    - Spread
    - Volumes
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), 
                              gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.suptitle(f"Dashboard — {product} (day {day})", fontsize=16, fontweight="bold", y=0.98)

    plot_orderbook(prices, trades, product, day=day, ax=axes[0])
    plot_spread(prices, product, day=day, ax=axes[1])
    plot_volumes(prices, product, day=day, ax=axes[2])

    plt.tight_layout()
    return fig


def plot_comparison(prices, trades):
    """Vue comparative des 2 produits côte à côte."""

    products = sorted(prices["product"].unique())
    n = len(products)

    fig, axes = plt.subplots(n, 1, figsize=(14, 5 * n))
    if n == 1:
        axes = [axes]

    fig.suptitle("Comparaison des produits — Day -1", fontsize=16, fontweight="bold", y=1.01)

    for i, product in enumerate(products):
        plot_orderbook(prices, trades, product, day=-1, ax=axes[i])

    plt.tight_layout()
    return fig


# =============================================================================
#  4. MAIN — Exécuter tout
# =============================================================================

if __name__ == "__main__":

    print("Chargement des données...")
    prices, trades = load_data()

    if len(prices) == 0:
        print("❌ Aucun fichier trouvé. Vérifie que les CSV sont dans le dossier courant.")
        exit()

    # Résumé texte
    print_summary(prices, trades)

    # Graphiques
    products = sorted(prices["product"].unique())
    print(f"\nGénération des graphiques pour : {products}")

    # 1. Vue comparative
    fig = plot_comparison(prices, trades)
    plt.savefig("comparison.png", dpi=150, bbox_inches="tight")
    print("  → comparison.png")

    # 2. Dashboard détaillé par produit
    for product in products:
        for day in [0]:
            pp = prices[(prices["product"] == product) & (prices["day"] == day)]
            if len(pp) == 0:
                continue
            fig = plot_full_dashboard(prices, trades, product, day=day)
            fname = f"dashboard_{product.lower()}_day{day}.png"
            plt.savefig(fname, dpi=150, bbox_inches="tight")
            print(f"  → {fname}")

    # 3. Distribution des trades
    fig, axes = plt.subplots(1, len(products), figsize=(6 * len(products), 4))
    if len(products) == 1:
        axes = [axes]
    for i, product in enumerate(products):
        plot_trade_distribution(trades, product, ax=axes[i])
    plt.tight_layout()
    plt.savefig("trade_distributions.png", dpi=150, bbox_inches="tight")
    print("  → trade_distributions.png")

    plt.show()
    print("\nTerminé !")
