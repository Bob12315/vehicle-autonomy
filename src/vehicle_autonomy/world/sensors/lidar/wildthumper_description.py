"""Small schematic only; the official Gazebo mesh stays outside the package."""


def schematic():
    body='<visual><origin xyz="0 0 .0145"/><geometry><box size=".38 .12 .025"/></geometry><material name="chassis"><color rgba=".7 .2 .1 1"/></material></visual>'
    body+='<visual name="mid360_mount_support"><origin xyz="0 0 .1085"/><geometry><cylinder radius=".009" length=".163"/></geometry></visual>'
    # The six wheel centres/radius are taken from the pinned official SDF.
    for x in (.15,0.,-.15):
        for y in (.12,-.12):
            z=-.04 if x==0. else -.03
            body+=f'<visual name="wheel_{x}_{y}"><origin xyz="{x} {y} {z}" rpy="1.57079632679 0 0"/><geometry><cylinder radius=".062" length=".062"/></geometry><material name="tyre"><color rgba=".08 .08 .08 1"/></material></visual>'
    return body
