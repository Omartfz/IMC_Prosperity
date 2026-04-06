# Stratégie Tutorial Round — Prosperity 4

## Résumé

Notre algo utilise une stratégie de **market making simple** sur les 2 produits du tutorial round. L'idée : estimer le "vrai prix" de chaque produit, acheter tout ce qui est proposé en dessous, vendre tout ce qui est demandé au-dessus, puis poster des ordres passifs pour capturer le spread.

## Produits

| Produit | Type | Fair value | Spread moyen | Méthode d'estimation |
|---------|------|-----------|-------------|---------------------|
| EMERALDS | Prix fixe | 10 000 | ~16 | Hard-codé (le prix ne bouge jamais) |
| TOMATOES | Random walk lent | ~4 993 | ~13 | Wall mid dynamique |

## Comment on estime le fair value

**EMERALDS** — Le wall mid est constant à 10 000 sur les 2 jours de données. On hard-code directement `fair = 10_000`.

**TOMATOES** — Le prix fluctue lentement (std ~20). On utilise le **wall mid** : la moyenne entre le bid le plus profond (bid wall) et l'ask le plus profond (ask wall) du book. Les market makers bots placent leurs ordres profonds autour du vrai prix, ce qui en fait un bon estimateur.

```
bid_wall = min(buy_orders.keys())      # bid le plus bas
ask_wall = max(sell_orders.keys())     # ask le plus haut
wall_mid = (bid_wall + ask_wall) / 2
```

## Logique de l'algo (à chaque itération)

```
Pour chaque produit :

  1. TAKING — prendre les bonnes affaires
     - Acheter tout ce qui est en vente SOUS le fair value
     - Vendre tout ce qui est demandé AU-DESSUS du fair value

  2. MAKING — poster des ordres passifs
     - Bid à best_bid + 1 (overbidding) → être servi en priorité
     - Ask à best_ask - 1 (undercutting) → idem côté vente
     - Jamais au-delà du fair value dans les deux cas

  3. POSITION LIMITS — vérifier partout
     - Max achat = limit - position
     - Max vente = limit + position
     - Si le total dépasse → TOUS les ordres rejetés
```

## Points techniques

- **Stateless** : l'environnement efface tout entre les appels. Pour l'instant on ne persiste rien (pas besoin pour cette stratégie simple).
- **Position limits** : supposées à 50 par produit (à vérifier dans le dashboard).
- **sell_orders négatifs** : les quantités dans `sell_orders` sont négatives. On fait `abs(qty)` ou `-qty` pour avoir le vrai volume.
- **Exécution instantanée** : pas de latence, nos ordres arrivent avant ceux des bots.

## Fichiers

| Fichier | Description |
|---------|-------------|
| `first_algo.py` | L'algo à uploader sur Prosperity |
| `visualize_data.py` | Script de visualisation des données CSV |

## Prochaines étapes

- Uploader l'algo sur le tutorial round et analyser les résultats
- Passer à la Phase 2 : gestion d'inventaire (aplatir la position quand elle est trop skewée), overbidding/undercutting plus agressif, et détection de patterns de bots
- Quand le Round 1 commence (14 avril) : analyser les nouveaux produits et adapter
