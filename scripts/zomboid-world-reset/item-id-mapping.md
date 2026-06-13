# Zomboid World Reset — Item ID Mapping

Resolved from the prod container (`zomboid-dedicated-server`), B42 game files at
`/home/steam/ZomboidDedicatedServer/media/scripts/generated/items/`.
All items confirmed present in the source files via `grep`. All IDs are in `module Base`.

---

## Melee Weapons

| Boon Description | Player(s) | Item ID | In-Game Display Name | Source Line |
|---|---|---|---|---|
| Hunting Knife | Bulbs | `Base.HuntingKnife` | Hunting Knife | weapon.txt:16731 |
| Machete | Emma, Curtis | `Base.Machete` | Machete | weapon.txt:13829 |
| Long-Handle Shovel | Vinny | `Base.Shovel2` | Shovel | weapon.txt:9341 |
| Pickaxe | RT-541 | `Base.PickAxe` | Pickaxe | weapon.txt:10286 |

**Note on Shovel2:** In B42, `Base.Shovel` is the spade-style short-handle tool (display: "Spade").
`Base.Shovel2` is the long-handle digging shovel (display: "Shovel"). `Shovel2` is the correct choice.

---

## Clothing

| Boon Description | Player | Item ID | In-Game Display Name | Sub? | Notes |
|---|---|---|---|---|---|
| Welder's overalls, one knee patched with duct tape | Bulbs | `Base.Boilersuit` | Coveralls | YES | No welder-specific overalls in vanilla B42; generic Coveralls is the closest one-piece work garment. Patch flavor is cosmetic only. |
| USPS postal worker parka with reflective stripes | Emma | `Base.Jacket_WhiteTINT` | Jacket | YES | No postal uniform in vanilla B42. Plain white jacket is the closest unremarkable outerwear. Reflective stripes and USPS branding are flavor only. |
| UK Wildcats hoodie with bloodstain on hem | Vinny | `Base.HoodieDOWN_WhiteTINT` | Hoodie | YES | No branded collegiate hoodie in vanilla B42. Generic white tint hoodie (dye-capable) is the substitute. Bloodstain flavor is cosmetic only. |
| Sweat-stained wide-brim cowboy hat | RT-541 | `Base.Hat_Cowboy` | Cowboy Hat | NO | Direct vanilla match. Sweat-stain is flavor only. |
| Clergy collar shirt with button missing | Curtis | `Base.Shirt_Priest` | Priest Shirt | NO | Direct vanilla match. Missing button is flavor only. |

---

## Firearms, Magazines, and Ammo

### Bulbs & RT-541 — M14 + 1 full mag (.308×20)

| Role | Item ID | In-Game Display Name | Qty | Notes |
|---|---|---|---|---|
| Rifle | `Base.AssaultRifle2` | M1A Rifle | 1 | B42 internal ID for M14/M1A |
| Magazine | `Base.M14Clip` | M1A Magazine | 1 | MaxAmmo=20; fires .308 |
| Ammo (loose) | `Base.308Bullets` | 7.62x51mm Round | 0 | 0 loose rounds — mag is given pre-filled |

**Give command note:** Spawn 1x `Base.AssaultRifle2` + 1x `Base.M14Clip` (full at spawn).

---

### Emma — M1911 + 1 full mag (.45×7)

| Role | Item ID | In-Game Display Name | Qty | Notes |
|---|---|---|---|---|
| Pistol | `Base.Pistol2` | M1911 Pistol | 1 | B42 internal ID for M1911 |
| Magazine | `Base.45Clip` | M1911 Auto Magazine | 1 | MaxAmmo=7; fires .45 ACP |
| Ammo (loose) | `Base.Bullets45` | .45 ACP Round | 0 | 0 loose rounds — mag is given pre-filled |

**Give command note:** Spawn 1x `Base.Pistol2` + 1x `Base.45Clip` (full at spawn).

---

### Vinny — Sawed-Off Double-Barrel Shotgun + 4 shells

| Role | Item ID | In-Game Display Name | Qty | Notes |
|---|---|---|---|---|
| Shotgun | `Base.DoubleBarrelShotgunSawnoff` | Sawed-off Double Barrel Shotgun | 1 | Break-action, MaxAmmo=2 |
| Shells | `Base.ShotgunShells` | 12g Round | 4 | Loose shells, count=6 per stack item |

**Give command note:** Spawn 1x `Base.DoubleBarrelShotgunSawnoff` + 4x `Base.ShotgunShells` (shells go into inventory; player loads manually).

---

### Curtis — Hunting Rifle + scope + 2× .308

| Role | Item ID | In-Game Display Name | Qty | Notes |
|---|---|---|---|---|
| Rifle | `Base.HuntingRifle` | MSR788 Rifle | 1 | Bolt-action, no detachable mag; internal capacity 4 rounds |
| Scope | `Base.x2Scope` | x2 Scope | 1 | Compatible attachment (confirmed in ModelWeaponPart) |
| Ammo | `Base.308Bullets` | 7.62x51mm Round | 2 | Loose rounds; loads directly into rifle |

**Give command note:** Spawn 1x `Base.HuntingRifle` + 1x `Base.x2Scope` + 2x `Base.308Bullets`.

---

## Substitutions Summary

Three clothing items have no direct vanilla equivalent and were substituted:

1. **Bulbs — Welder's Overalls** → `Base.Boilersuit` ("Coveralls")
   - Reason: B42 has no welder-specific overalls. `Boilersuit` is the only full-body work coverall in vanilla. The "duct tape patched knee" descriptor is flavor — no mechanical representation.

2. **Emma — USPS Postal Worker Parka** → `Base.Jacket_WhiteTINT` ("Jacket")
   - Reason: No postal/USPS uniform exists in vanilla B42. `Jacket_WhiteTINT` is a plain, dye-capable jacket that best represents non-military outerwear. "Reflective stripes" and USPS branding are flavor only.

3. **Vinny — UK Wildcats Hoodie** → `Base.HoodieDOWN_WhiteTINT` ("Hoodie")
   - Reason: No branded collegiate hoodies exist in vanilla B42. The white-tint hoodie is dye-capable and represents a generic pullover hoodie. "Bloodstain on hem" is flavor only.

All other items — `Hat_Cowboy` (RT-541) and `Shirt_Priest` (Curtis) — are direct vanilla matches with no substitution needed.

---

## Source Files Referenced

- Weapons: `/home/steam/ZomboidDedicatedServer/media/scripts/generated/items/weapon.txt`
- Normal Items (ammo/mags): `/home/steam/ZomboidDedicatedServer/media/scripts/generated/items/normal.txt`
- Clothing: `/home/steam/ZomboidDedicatedServer/media/scripts/generated/items/clothing.txt`
- Weapon Parts (scopes): `/home/steam/ZomboidDedicatedServer/media/scripts/generated/items/weaponpart.txt`
- Display Name Verification: `/home/steam/ZomboidDedicatedServer/media/lua/shared/Translate/EN/ItemName.json`
