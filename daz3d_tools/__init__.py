# -*- coding: utf-8 -*-
# Copyright 2023 UuuNyaa <UuuNyaa@gmail.com>, boyleo https://github.com/boyleo/daz2arp
# This file is part of Daz3D Tools.

# Daz3D Tools is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Daz3D Tools is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


from . import auto_load
import bpy

bl_info = {
    "name": "Daz3D Tools",
    'author': 'UuuNyaa',
    "version": (2, 0, 0),
    "blender": (3, 3, 0),
    'location': 'View3D > Object > Convert Daz armature to AutoRig Pro',
    "description": "Convert Daz 3D models to AutoRig Pro with one click",
    'tracker_url': 'https://github.com/UuuNyaa/blender_daz3d_tools/issues',
    'support': 'COMMUNITY',
    'category': 'Object'
}


auto_load.init()


def register():
    bpy.app.handlers.load_post.append(_load_handler)
    auto_load.register()


def unregister():
    auto_load.unregister()
    bpy.app.handlers.load_post.remove(_load_handler)


def _erc_keyed(var, min, max, normalized_dist, dist):
    """Converts difference to a 0 to 1 range
    see: https://github.com/daz3d/DazToBlender/blob/1bcb95f6e0e4c901a1f99c350e6334cfae2cf96c/Blender/appdata_common/Blender%20Foundation/Blender/BLENDER_VERSION/scripts/addons/DTB/__init__.py#L294
    """
    if dist < 0:
        if max <= var <= min:
            return abs((var - min) / dist)
        elif max >= var:
            return 1
        else:
            return 0
    if min <= var <= max:
        return abs((var - min * normalized_dist) / dist)
    elif max <= var:
        return 1
    else:
        return 0


@bpy.app.handlers.persistent
def _load_handler(dummy):
    dns = bpy.app.driver_namespace
    if not hasattr(dns, 'erc_keyed'):
        dns['erc_keyed'] = _erc_keyed
