"""shopcad: a small headless CAD framework for shop build plans.

A plan module under cad/plans/ exposes:

    DEFAULTS: dict of the drawing-set numbers (inches, counts)
    STATES:   dict name -> state dict (which doors are open, what is flipped)
    build(P, state) -> shopcad.geometry.Scene
    checks(P) -> list of (name, ok, detail)

shopcad.export turns that into STEP, GLB, mesh JSON and a viewer page inside
the cadquery/cadquery container; shopcad.fusion emits a Fusion 360 script
folder from the same module; cad/run.sh drives both plus the headless
renders.
"""
