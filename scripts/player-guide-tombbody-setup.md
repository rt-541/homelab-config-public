# TombBody + SPNCC Local Setup Guide

Follow these steps to set up the body customisation mods locally so you can
test them in single player before joining the server.

## Step 1: Subscribe to the Workshop Items

Open each link in Steam and click **Subscribe**:

1. [Spongie's Character Customisation](https://steamcommunity.com/sharedfiles/filedetails/?id=3414634809)
2. [Spongie's Character Customisation Details HD](https://steamcommunity.com/sharedfiles/filedetails/?id=3672913009)
3. [Tomb's Player Body Overhaul](https://steamcommunity.com/sharedfiles/filedetails/?id=3429790870)
4. [Tomb's Player Body Overhaul - Compatibility](https://steamcommunity.com/sharedfiles/filedetails/?id=3431734923)
5. [Tomb's Wardrobe ALT](https://steamcommunity.com/sharedfiles/filedetails/?id=3616536783)

## Step 2: Enable and Order the Mods

1. Launch Project Zomboid
2. Go to the **Mods** screen from the main menu
3. Enable all the mods you just subscribed to
4. Set the load order — the mods should be ordered like this (top = loads first):

```
... (your other mods) ...
SpnCharCustom
SPNCC
SpnCharCustomDetails
SPNCCDetails
SpnCharCustomDetailsHD
SPNCCDetailsHD
SpnCharCustomFaces
SPNCCFaces
TombBody
TombBodyCustom
TombBodyTexNUDE
TombWardrobeALT
TombBodyCompat          <-- always LAST
```

> **Important:** Only enable ONE texture pack — use `TombBodyTexNUDE`.
> Do NOT also enable `TombBodyTex` or `TombBodyTexDOLL`.
>
> Only enable ONE wardrobe — use `TombWardrobeALT`.
> Do NOT also enable `TombWardrobeALTVanilla`.

5. **Restart the game** after enabling the mods (required for retextures)

## Step 3: Test in Single Player

1. Start a **new single player game**
2. On the character creation screen you should see new body customisation options:
   - Face selection
   - Body details
   - Body hair / stubble
   - Muscle visuals
3. Create a character and verify the nude body textures are working
4. If everything looks good, you're ready to join the server

## Joining the Server

When you connect to the server, it will force-download the workshop mods
automatically. If you already have them installed locally with the correct
load order, you're all set.

On first login after the mods are added to the server, the character
customisation window will open automatically so you can set up your
character's body options.

## Troubleshooting

- **Mods not showing up?** Restart the game after subscribing.
- **Still getting errors?** Unsubscribe and resubscribe to the mods.
- **Retextures not loading?** A full game restart is required — not just
  returning to the main menu.
